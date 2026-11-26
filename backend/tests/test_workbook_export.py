import json
import unittest
from copy import copy, deepcopy
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

    def test_unmet_geriatric_request_and_assigned_posting_show_compact_ranges(self):
        content, draft = fixture()
        outcome = draft['residents'][0]['requests'][0]
        outcome.update(request={'posting_request': 'SKH Geriatric Psychiatry', 'period': 'July - December 2027'},
                       requested_durations=[6], assigned=[{'label': 'NUH Child and Geriatric Psychiatry',
                                                           'months': [f'2028-{month:02d}' for month in range(1, 7)]}])

        output, _ = export_workbook(content, 2027, draft)
        note = load_workbook(BytesIO(output))['Jul 2027 - Jun 2028']['D3'].comment
        self.assertEqual(note.author, 'Original author')
        self.assertEqual(note.text.splitlines()[:5], [
            'Keep this note', '',
            'Request not met: SKH Geriatric Psychiatry (Jul–Dec 2027)',
            'Assigned: NUH Child and Geriatric Psychiatry (Jan–Jun 2028)',
            'Reason: Outstanding training',
        ])

    def test_request_alternatives_keep_distinct_durations_and_unclear_period_text(self):
        content, draft = fixture()
        outcome = draft['residents'][0]['requests'][0]
        outcome['alternatives'] = [
            {'request': {'posting_request': 'Option A', 'period': ' '}, 'requested_durations': [3, 6], 'requested_months': 6},
            {'request': {'posting_request': 'Option B', 'period': 'October 2027 – March 2028'}, 'requested_months': 3},
            {'request': {'posting_request': 'Option C', 'period': 'June 2028'}},
            {'request': {'posting_request': 'Option D', 'period': 'After exams'}, 'requested_months': 1},
            {'request': {'posting_request': 'Option E', 'period': '  July - December 2027  '},
             'reason': 'Period is unclear or outside the planning year', 'requested_durations': [6]},
        ]

        output, _ = export_workbook(content, 2027, draft)
        note = load_workbook(BytesIO(output))['Jul 2027 - Jun 2028']['D3'].comment.text
        self.assertIn('Request not met: Option A (Any time in planning year · 3 or 6 months) OR '
                      'Option B (Oct 2027–Mar 2028 · 3 months) OR Option C (Jun 2028) OR '
                      'Option D (After exams · 1 month) OR Option E (  July - December 2027   · 6 months)', note)

    def test_assigned_and_completed_month_ranges_keep_gaps_and_postings_separate(self):
        content, draft = fixture()
        person = draft['residents'][0]
        person['requests'][0]['assigned'] = [
            {'label': 'First posting', 'months': ['2028-03', '2028-01', '2027-12', '2028-01']},
            {'label': 'Second posting', 'months': ['2028-04']},
        ]
        for month in person['months']:
            if month['month'] in {'2027-12', '2028-01', '2028-03'}:
                month['status'] = 'requirements_completed'

        output, _ = export_workbook(content, 2027, draft)
        note = load_workbook(BytesIO(output))['Jul 2027 - Jun 2028']['D3'].comment.text
        self.assertIn('Assigned: First posting (Dec 2027–Jan 2028, Mar 2028); Second posting (Apr 2028)', note)
        self.assertIn('Draft projection: requirements completed; unallocated months remain blank '
                      '(Nov 2027–Jan 2028, Mar 2028).', note)

    def test_dated_miss_shades_only_requested_cells_and_appends_first_cell_note(self):
        content, draft = fixture()
        book = load_workbook(BytesIO(content))
        sheet = book['Jul 2027 - Jun 2028']
        sheet['M3'] = '=1+1'
        sheet['M3'].font = Font(color='FF123456', italic=True)
        sheet['M3'].comment = Comment('Keep January note', 'Planner')
        stream = BytesIO()
        book.save(stream)
        person = draft['residents'][0]
        request = {'status': 'not_met', 'request': {'posting_request': 'IMH EPIP', 'period': 'Jan - Jun 2028'}}
        person['requests'] = [request, {**request, 'duplicate_of': 0},
                              {**request, 'status': 'pending', 'request': {'posting_request': 'Pending', 'period': 'Jul - Sep 2027'}},
                              {**request, 'alternatives': [{**request, 'status': 'met'}]}]
        output, _ = export_workbook(stream.getvalue(), 2027, draft)
        exported = load_workbook(BytesIO(output))[sheet.title]
        for cell in exported['G3:L3'][0]:
            self.assertNotEqual(cell.fill.fgColor.rgb, 'FFFBE1DF')
        for cell in exported['M3:R3'][0]:
            self.assertEqual((cell.fill.patternType, cell.fill.fgColor.rgb), ('solid', 'FFFBE1DF'))
        self.assertEqual(exported['M3'].value, '=1+1')
        self.assertEqual(exported['M3'].font, copy(sheet['M3'].font))
        self.assertEqual(exported['M3'].comment.text, 'Keep January note\n\nRequested IMH EPIP for Jan–Jun 2028. No matching assignment.')
        self.assertTrue(all(cell.comment is None for cell in exported['N3:R3'][0]))
        self.assertEqual(exported['D3'].font.color.rgb, 'FFFF0000')

    def test_any_time_request_highlights_the_year_for_wrong_site_different_posting_or_no_assignment(self):
        def edit(book):
            sheet = book['Jul 2027 - Jun 2028']
            sheet.unmerge_cells('H3:I3')
            sheet['G3'] = None
            book['Postings'].append(['R3', 'Core', 'NUH', 'Continuity Clinic', 12, 12, 'Continuity Clinic'])
        content = structured_workbook_bytes(edit)
        workbook = parse_workbook(content)
        catalogue = posting_catalogue(workbook['postings'])
        clinic = next(o for o in catalogue if o['label'] == 'NUH Continuity Clinic')
        for assigned, period in [(clinic, None), (catalogue[0], None), (None, None), (None, 'After exams')]:
            with self.subTest(assignment=assigned and assigned['label'], period=period):
                person = {key: workbook['residents'][0][key] for key in ('source', 'name', 'mcr')}
                dates = [m['month'] for m in workbook['months']]
                person['months'] = [dict(month=m, status='posting', target=assigned, label=assigned['label'])
                                    if assigned else dict(month=m, status='outside_draft_scope') for m in dates]
                person['requests'] = [{'request': {'posting_request': 'IMH Continuity Clinic', 'period': period},
                                       'status': 'not_met', 'requested_months': 12,
                                       'option_keys': [['r3.continuity_clinic', 'IMH', 'IMH Continuity Clinic']],
                                       'assigned': [{'label': assigned['label'], 'months': dates}] if assigned is clinic else []}]
                output, _ = export_workbook(content, 2027, {'status': 'feasible', 'cutoff': '2027-06', 'residents': [person]})
                sheet = load_workbook(BytesIO(output))['Jul 2027 - Jun 2028']
                self.assertTrue(all(cell.fill.fgColor.rgb == 'FFFBE1DF' for cell in sheet['G3:R3'][0]))
                timing = 'for After exams' if period else 'at any time in the planning year'
                self.assertIn(f'Requested IMH Continuity Clinic {timing}', sheet['G3'].comment.text)
                self.assertTrue(all(cell.comment is None for cell in sheet['H3:R3'][0]))

    def test_partial_match_only_marks_missed_months_and_shared_first_cell_keeps_both_notes(self):
        content, draft = fixture()
        person = draft['residents'][0]
        target = person['months'][3]['target']
        target.update(requirement_id='r5.elective', institution='IMH')
        key = [target['requirement_id'], target['institution'], target['label']]
        request = {'status': 'not_met', 'request': {'posting_request': target['label'], 'period': 'Oct - Dec 2027'},
                   'assigned': [{'label': target['label'], 'months': ['2027-10', '2027-12']}],
                   'option_keys': [key], 'matched_months': ['2027-12']}
        person['requests'] = [request, {'status': 'not_met', 'request': {'posting_request': 'Other posting', 'period': 'November 2027'}}]
        output, _ = export_workbook(content, 2027, draft)
        sheet = load_workbook(BytesIO(output))['Jul 2027 - Jun 2028']
        self.assertNotEqual(sheet['J3'].fill.fgColor.rgb, 'FFFBE1DF')
        self.assertNotEqual(sheet['L3'].fill.fgColor.rgb, 'FFFBE1DF')
        self.assertEqual(sheet['K3'].fill.fgColor.rgb, 'FFFBE1DF')
        self.assertIn(f"Requested {target['label']} for Oct–Dec 2027.", sheet['K3'].comment.text)
        self.assertIn("Requested Other posting for Nov 2027.", sheet['K3'].comment.text)

    def test_pending_and_met_alternative_are_not_red_and_new_notes_are_readable(self):
        content, draft = fixture()
        w = load_workbook(BytesIO(content))
        w['Jul 2027 - Jun 2028']['D3'].comment = None
        stream = BytesIO(); w.save(stream); content = stream.getvalue()
        outcome = draft['residents'][0]['requests'][0]
        outcome['status'] = 'pending'
        draft['residents'][0]['requests'].append({**deepcopy(outcome), 'status': 'not_met', 'alternatives': [{'status': 'met'}]})
        output, retained = export_workbook(content, 2027, draft)
        s = load_workbook(BytesIO(output))['Jul 2027 - Jun 2028']
        self.assertEqual(s['D3'].font.color.rgb, '00003366')
        self.assertEqual(s['D3'].comment.text.count('Requested posting'), 1)
        self.assertIn('pending review', s['D3'].comment.text)

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
