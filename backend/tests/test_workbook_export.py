import json
import unittest
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font

from main import app
from workbook_export import export_workbook
from workbook_import import MAX_UPLOAD_BYTES, WorkbookError, parse_workbook, posting_catalogue
from tests.test_workbook_import import structured_workbook_bytes


def fixture():
    def edit(w):
        s = w['Jul 2027 - Jun 2028']
        s['D3'].comment = Comment('Keep this note', 'Original author')
        s['D3'].font = Font(name='Arial', bold=True, italic=True, color='003366')
        s['K3'] = None
        s['A3'] = '=1+2'
        s['D4'], s['E4'], s['F4'] = 'Skipped resident', 'M99999A', 'R4'
        s['G4'] = 'Original posting'
        w['Postings']['C5'] = '=1+1'
        w['Postings']['C5'].data_type = 's'
    content = structured_workbook_bytes(edit)
    wb = parse_workbook(content)
    person = wb['residents'][0]
    option = next(o for o in posting_catalogue(wb['postings']) if o['category'] == 'elective')
    months = [{'month': m['month'], 'status': 'outside_draft_scope', 'label': None} for m in wb['months']]
    months[0]['status'] = 'loa'
    months[3].update(status='posting', label=option['label'], target=option)
    months[4]['status'] = 'requirements_completed'
    draft = {'status': 'feasible', 'cutoff': '2027-06', 'residents': [
        {'source': person['source'], 'name': person['name'], 'mcr': person['mcr'], 'projected_year': 'R4,R5', 'months': months,
         'requests': [{'request': {'posting_request': 'Requested posting', 'period': 'October 2027'}, 'status': 'not_met',
                       'reason': 'Outstanding training', 'assigned': [{'label': option['label'], 'months': ['2027-10']}]}]}]}
    return content, draft


def reopen_request_export(outcome, assignments, *, july_note=None):
    def prepare(workbook):
        sheet = workbook['Jul 2027 - Jun 2028']
        sheet.unmerge_cells('H3:I3')
        for cell in sheet['G3:R3'][0]:
            cell.value = None
        if july_note:
            sheet['G3'].comment = Comment(july_note, 'Planner')
        workbook['Postings'].append(['R3', 'Core', 'NUH', 'Continuity Clinic', 12, 12, 'Continuity Clinic'])
        workbook['Postings']['C6'] = 'NUH'  # Combined Child and Geriatric core posting.

    content = structured_workbook_bytes(prepare)
    workbook = parse_workbook(content)
    options = {option['label']: option for option in posting_catalogue(workbook['postings'])}
    resident = {key: workbook['residents'][0][key] for key in ('name', 'mcr', 'source')}
    resident['requests'] = [outcome]
    resident['months'] = [
        {'month': date['month'], 'status': 'posting', 'label': label, 'target': options[label]}
        if label else {'month': date['month'], 'status': 'outside_draft_scope'}
        for date, label in zip(workbook['months'], assignments, strict=True)]
    draft = {'status': 'feasible', 'cutoff': '2027-06', 'residents': [resident]}
    output, _ = export_workbook(content, 2027, draft)
    return load_workbook(BytesIO(output))[workbook['target_sheet']]


class ExportTests(unittest.TestCase):
    def test_large_edited_draft_without_warning_baseline_exports_the_edit(self):
        sheet = 'Jul 2027 - Jun 2028'

        def populate(workbook):
            for row in range(4, 168):
                workbook[sheet].cell(row, 4, f'Resident {row - 2}')
                workbook[sheet].cell(row, 6, 'R2')

        content = structured_workbook_bytes(populate)
        workbook = parse_workbook(content)
        options = posting_catalogue(workbook['postings'])
        normal = next(option for option in options if option['category'] == 'elective')
        edited = next(option for option in options if option['label'] == 'IMH Child and Geriatric Psychiatry')
        residents = []
        for person in workbook['residents']:
            preserved = {key: person[key] for key in ('source', 'name', 'mcr')}
            target = edited if person['source']['row'] == 4 else normal
            residents.append({**preserved, 'projected_year': 'R2', 'months': [
                {'month': month['month'], 'status': 'loa' if month['status'] == 'loa' else 'posting',
                 'block_start': month['month'], 'label': target['label'], 'target': target}
                for month in person['postings']]})
        self.assertEqual(len(residents), 165)
        people = [{key: person[key] for key in ('source', 'name', 'mcr')} for person in residents]
        overflows = [{'month': month['month'], 'residents': people, 'assigned': len(residents), 'max': 24,
                      'source': normal['source'], 'label': normal['label'], 'category': normal['category']}
                     for month in workbook['months']]
        draft = {'status': 'edited', 'cutoff': '2027-06', 'residents': residents, 'capacity_overflows': overflows}
        payload = json.dumps(draft, separators=(',', ':')).ljust(1_051_278)
        self.assertEqual(len(payload.encode('utf-8')), 1_051_278)

        response = TestClient(app).post('/api/export', files={'originalFile': ('Example.xlsx', content)},
                                        data={'target_year': '2027', 'draft': payload})
        self.assertEqual(response.status_code, 200, response.text if response.status_code != 200 else '')
        self.assertEqual(response.headers['content-type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        exported = load_workbook(BytesIO(response.content))
        self.assertEqual(exported[sheet]['G4'].value, edited['label'])
        self.assertEqual(exported[sheet]['G167'].value, normal['label'] + ' (Elective)')

    def test_draft_part_one_byte_over_export_limit_is_rejected(self):
        content, draft = fixture()
        payload = json.dumps(draft).ljust(2 * 1024 * 1024 + 1)
        response = TestClient(app).post('/api/export', files={'originalFile': ('Example.xlsx', content)},
                                        data={'target_year': '2027', 'draft': payload})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn('maximum size of 2048KB', response.json()['detail'])

    def test_export_preserves_form_validation_and_workbook_upload_limit(self):
        client = TestClient(app)
        content, draft = fixture()
        files = {'originalFile': ('Example.xlsx', content)}
        fields = {'target_year': '2027', 'draft': json.dumps(draft)}
        for invalid in ({'target_year': '2027'}, {**fields, 'target_year': 'bad'}, {**fields, 'draft': '{'}):
            with self.subTest(fields=invalid.keys()):
                response = client.post('/api/export', files=files, data=invalid)
                self.assertEqual(response.status_code, 422, response.text)

        response = client.post('/api/export', headers={'Content-Type': 'multipart/form-data; boundary=example'},
                               content=b'bad multipart')
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()['detail'], 'Invalid multipart data.')

        response = client.post('/api/export', data=fields,
                               files={'originalFile': ('Example.xlsx', b'x' * (MAX_UPLOAD_BYTES + 1))})
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(response.json()['detail'], 'Workbook exceeds the 10 MB upload limit')

    def test_only_planned_cells_year_and_name_annotations_change(self):
        content, draft = fixture()
        output, retained = export_workbook(content, 2027, draft)
        a, b = load_workbook(BytesIO(content)), load_workbook(BytesIO(output))
        self.assertEqual(a.sheetnames, b.sheetnames)
        changed = {'D3', 'F3', 'J3'}
        for s in a:
            t = b[s.title]
            self.assertEqual(str(s.merged_cells), str(t.merged_cells))
            for row in s:
                for c in row:
                    if s.title == 'Jul 2027 - Jun 2028' and c.coordinate in changed:
                        continue
                    other = t[c.coordinate]
                    self.assertEqual((c.value, c.data_type, c._style, c.comment.text if c.comment else None),
                                     (other.value, other.data_type, other._style, other.comment.text if other.comment else None))
        s = b['Jul 2027 - Jun 2028']
        self.assertEqual(s['F3'].value, 'R4,R5')
        self.assertEqual(s['J3'].value, draft['residents'][0]['months'][3]['label'] + ' (Elective)')
        self.assertEqual(s['L3'].value, 'Posting')
        self.assertEqual(s['J3'].data_type, 's')
        self.assertTrue(s['J3'].value.startswith('='))
        self.assertIsNone(s['K3'].value)
        self.assertIn('requirements completed', s['D3'].comment.text)
        self.assertIn('Keep this note', s['D3'].comment.text)
        self.assertIn('Requested posting', s['D3'].comment.text)
        self.assertIn('Oct 2027', s['D3'].comment.text)
        self.assertIn('Assigned:', s['D3'].comment.text)
        self.assertEqual(s['D3'].font.color.rgb, 'FFFF0000')
        self.assertTrue(s['D3'].font.bold)
        self.assertTrue(s['D3'].font.italic)
        self.assertEqual(s['D3'].font.name, 'Arial')
        with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(output)) as after:
            differences = [n for n in before.namelist() if before.read(n) != after.read(n)]
            self.assertEqual(set(differences), {'xl/worksheets/sheet2.xml', 'xl/styles.xml', 'xl/comments/comment1.xml',
                                                'xl/drawings/commentsDrawing1.vml'})
        imported = parse_workbook(output)
        self.assertEqual(imported['residents'][0]['postings'][3]['status'], 'posting')
        self.assertEqual(imported['residents'][0]['postings'][0]['value'], 'LOA')

    def test_dated_request_shows_compact_ranges_and_shades_only_the_requested_months(self):
        assigned = 'NUH Child and Geriatric Psychiatry'
        outcome = {'status': 'not_met', 'request': {'posting_request': 'SKH Geriatric Psychiatry', 'period': 'Jul - Dec 2027'},
                   'requested_months': 6, 'assigned': [{'label': assigned, 'months': [f'2028-{m:02d}' for m in range(1, 7)]}]}
        sheet = reopen_request_export(outcome, [None] * 6 + [assigned] * 6, july_note='Keep July note')
        self.assertIn('SKH Geriatric Psychiatry (Jul–Dec 2027)', sheet['D3'].comment.text)
        self.assertIn('Assigned: NUH Child and Geriatric Psychiatry (Jan–Jun 2028)', sheet['D3'].comment.text)
        self.assertEqual([c.column_letter for c in sheet['G3:R3'][0] if c.fill.fgColor.rgb == 'FFFBE1DF'],
                         list('GHIJKL'))
        self.assertIn('Keep July note\n\nRequested SKH Geriatric Psychiatry for Jul–Dec 2027.', sheet['G3'].comment.text)
        self.assertTrue(all(c.comment is None for c in sheet['H3:R3'][0]))

    def test_undated_unmet_clinic_request_highlights_the_whole_planning_year(self):
        outcome = {'status': 'not_met', 'request': {'posting_request': 'IMH Continuity Clinic', 'period': None}}
        sheet = reopen_request_export(outcome, ['NUH Continuity Clinic'] * 6 + ['TTSH General Medicine'] * 3 + [None] * 3)
        self.assertTrue(all(c.fill.fgColor.rgb == 'FFFBE1DF' for c in sheet['G3:R3'][0]))
        self.assertIn('Requested IMH Continuity Clinic at any time in the planning year', sheet['G3'].comment.text)
        self.assertTrue(all(c.comment is None for c in sheet['H3:R3'][0]))

    def test_partial_match_keeps_the_gap_in_the_note_and_shades_only_the_miss(self):
        clinic = 'NUH Continuity Clinic'
        outcome = {'status': 'not_met', 'request': {'posting_request': clinic, 'period': 'Dec 2027 - Mar 2028'},
                   'assigned': [{'label': clinic, 'months': ['2027-12', '2028-01', '2028-03']}],
                   'matched_months': ['2027-12', '2028-01', '2028-03']}
        sheet = reopen_request_export(outcome, [None] * 5 + [clinic, clinic, None, clinic] + [None] * 3)
        self.assertIn('Assigned: NUH Continuity Clinic (Dec 2027–Jan 2028, Mar 2028)', sheet['D3'].comment.text)
        self.assertEqual([c.column_letter for c in sheet['G3:R3'][0] if c.fill.fgColor.rgb == 'FFFBE1DF'], ['N'])

    def test_pending_and_met_alternative_are_not_red_and_new_notes_are_readable(self):
        content, draft = fixture()
        w = load_workbook(BytesIO(content))
        w['Jul 2027 - Jun 2028']['D3'].comment = None
        stream = BytesIO(); w.save(stream); content = stream.getvalue()
        outcome = draft['residents'][0]['requests'][0]
        outcome.update(status='pending', requested_durations=[3, 6])
        draft['residents'][0]['requests'].append({**deepcopy(outcome), 'status': 'not_met', 'alternatives': [{'status': 'met'}]})
        output, retained = export_workbook(content, 2027, draft)
        s = load_workbook(BytesIO(output))['Jul 2027 - Jun 2028']
        self.assertEqual(s['D3'].font.color.rgb, '00003366')
        self.assertEqual(s['D3'].comment.text.count('Requested posting'), 1)
        self.assertIn('pending review', s['D3'].comment.text)
        self.assertIn('Oct 2027 · 3 or 6 months', s['D3'].comment.text)

    def test_blank_month_merge_is_opened_but_existing_note_merge_is_preserved(self):
        content, draft = fixture()
        w = load_workbook(BytesIO(content)); s = w['Jul 2027 - Jun 2028']
        s['J3'] = None; s['K3'] = None; s['L3'] = None
        s['J3'].alignment = Alignment(wrap_text=True)
        s.merge_cells('J3:L3')
        draft['residents'][0]['months'][5].update(draft['residents'][0]['months'][3], month='2027-12')
        stream = BytesIO(); w.save(stream); content = stream.getvalue()
        output, retained = export_workbook(content, 2027, draft)
        s = load_workbook(BytesIO(output))['Jul 2027 - Jun 2028']
        self.assertNotIn('J3:L3', str(s.merged_cells))
        self.assertIn('H3:I3', str(s.merged_cells))
        self.assertTrue(s['J3'].value.endswith('(Elective)'))
        self.assertIsNone(s['K3'].value)
        self.assertTrue(s['L3'].alignment.wrap_text)
        invalid = deepcopy(draft)
        invalid['residents'][0]['months'][1].update(invalid['residents'][0]['months'][3], month='2027-08')
        _, retained = export_workbook(content, 2027, invalid)
        self.assertEqual(retained, ['Example Resident'])

    def test_merged_note_row_is_unchanged_and_other_residents_export_with_warning(self):
        content, draft = fixture()
        person = draft['residents'][0]
        person['months'][1].update(person['months'][3], month='2027-08')
        other = deepcopy(person)
        other.update(source={'sheet': 'Jul 2027 - Jun 2028', 'row': 4}, name='Skipped resident', mcr='M99999A', projected_year='R5', requests=[])
        for index, month in enumerate(other['months']):
            if index != 3:
                month.update(status='outside_draft_scope', label=None)
        draft['residents'].append(other)
        output, retained = export_workbook(content, 2027, draft)
        self.assertEqual(retained, ['Example Resident'])
        a = load_workbook(BytesIO(content))['Jul 2027 - Jun 2028']
        b = load_workbook(BytesIO(output))['Jul 2027 - Jun 2028']
        for cell in a[3]:
            other_cell = b[cell.coordinate]
            self.assertEqual((cell.value, cell._style, cell.comment.text if cell.comment else None),
                             (other_cell.value, other_cell._style, other_cell.comment.text if other_cell.comment else None))
        self.assertTrue(b['J4'].value.endswith('(Elective)'))
        self.assertEqual(b['F4'].value, 'R5')
        with ZipFile(BytesIO(content)) as original, ZipFile(BytesIO(output)) as exported:
            import re
            row = rb'<row\b(?=[^>]*\br="3")[^>]*>.*?</row>'
            self.assertEqual(re.search(row, original.read('xl/worksheets/sheet2.xml'))[0],
                             re.search(row, exported.read('xl/worksheets/sheet2.xml'))[0])
            self.assertEqual(original.read('xl/comments/comment1.xml'), exported.read('xl/comments/comment1.xml'))
        response = TestClient(app).post('/api/export', files={'originalFile': ('Example.xlsx', content)}, data={'target_year': '2027', 'draft': json.dumps(draft)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.headers['x-export-retained-residents']), retained)

    def test_threaded_name_note_preserves_original_text_and_all_other_parts(self):
        content, draft = fixture()
        data = BytesIO()
        with ZipFile(BytesIO(content)) as original, ZipFile(data, 'w') as modified:
            for info in original.infolist():
                value = original.read(info.filename)
                if info.filename == 'xl/worksheets/_rels/sheet2.xml.rels':
                    value = value.replace(b'</Relationships>', b'<Relationship Id="thread1" Type="http://schemas.microsoft.com/office/2017/10/relationships/threadedComment" Target="../threadedComments/threadedComment1.xml"/></Relationships>')
                modified.writestr(info, value)
            modified.writestr('xl/threadedComments/threadedComment1.xml', '<ThreadedComments xmlns="http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments"><threadedComment ref="D3" personId="original-person" id="original-id"><text>Original threaded note</text></threadedComment></ThreadedComments>')
        content = data.getvalue()
        output, retained = export_workbook(content, 2027, draft)
        with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(output)) as after:
            thread = after.read('xl/threadedComments/threadedComment1.xml').decode()
            self.assertIn('Original threaded note', thread)
            self.assertIn('Draft export', thread)
            self.assertIn('Requested posting', thread)
            self.assertIn('id="original-id"', thread)
            for name in before.namelist():
                if name not in {'xl/worksheets/sheet2.xml', 'xl/styles.xml', 'xl/comments/comment1.xml',
                                'xl/drawings/commentsDrawing1.vml', 'xl/threadedComments/threadedComment1.xml'}:
                    self.assertEqual(before.read(name), after.read(name), name)

    def test_payload_mismatches_are_rejected_and_download_has_filename(self):
        content, draft = fixture()
        client = TestClient(app)
        for mutate in [lambda d: d.update(cutoff='2026-06'), lambda d: d['residents'][0]['source'].update(row=999),
                       lambda d: d['residents'][0]['months'][3].update(month='2028-07'),
                       lambda d: d['residents'][0]['months'][3]['target'].update(source={'sheet': 'Other', 'row': 3})]:
            invalid = deepcopy(draft); mutate(invalid)
            with self.assertRaises(WorkbookError):
                export_workbook(content, 2027, invalid)
            response = client.post('/api/export', files={'originalFile': ('Example.xlsx', content)}, data={'target_year': '2027', 'draft': json.dumps(invalid)})
            self.assertEqual(response.status_code, 422)
        response = client.post('/api/export', files={'originalFile': ('Example.xlsx', content)}, data={'target_year': '2027', 'draft': json.dumps(draft)})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Example%20-%20Draft%202027-2028.xlsx', response.headers['content-disposition'])
        self.assertIn('spreadsheetml.sheet', response.headers['content-type'])
        self.assertTrue(response.content.startswith(b'PK'))
        with self.assertRaises(WorkbookError):
            export_workbook(content, 2026, draft)


if __name__ == '__main__':
    unittest.main()
