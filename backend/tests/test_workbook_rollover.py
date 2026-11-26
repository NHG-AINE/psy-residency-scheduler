import json
import unittest
from datetime import datetime
from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName

from history_review import ReviewStore, evaluate_review
from main import app
from requirement_ledger import build_requirement_ledger
from workbook_export import export_workbook
from workbook_import import WorkbookError, parse_workbook, posting_catalogue
from workbook_rollover import prepare_next_workbook
from tests.test_workbook_import import structured_workbook_bytes


LATEST = 'Jul 2027 - Jun 2028'
NEXT = 'Jul 2028 - Jun 2029'
MEDICINE = 'NUH Medicine & Neurology'
INPATIENT = 'IMH Inpatient Psychiatry'
STORE = ReviewStore(version=1, decisions=[])


def fixture(*, next_sheet=False, request_notes=False):
    def populate(workbook):
        workbook.remove(workbook['Jul 2026 - Jun 2027'])
        latest = workbook[LATEST]
        latest['A2'] = 'Residency Intake'
        latest['B2'] = 'MOM Number'
        latest['C2'] = 'Email'
        latest.unmerge_cells('H3:I3')
        latest.freeze_panes = 'G3'
        latest.column_dimensions['D'].width = 31
        latest['D3'].font = Font(name='Arial', bold=True, color='FF0000')
        latest['D3'].comment = Comment('Existing note', 'Planner')
        latest['G3'].fill = PatternFill('solid', fgColor='FBE1DF')
        latest['H3'].fill = PatternFill('solid', fgColor='DDEEFF')
        latest['J3'].alignment = Alignment(wrap_text=True)
        latest.row_dimensions[3].height = 23
        requests = workbook['Requests']
        requests['D3'] = 'Continuation is also an old request'
        requests['D3'].alignment = Alignment(wrap_text=True)
        requests.freeze_panes = 'D2'
        requests['J3'] = 'Keep layout note outside request fields'
        if request_notes:
            for coord, note in [('D1', 'Request heading'), ('D3', 'Old request note'),
                                ('D4', 'Old note on an empty cell'), ('J3', 'Layout note')]:
                requests[coord].comment = Comment(note, 'Planner')
            requests['J3'].hyperlink = '#Requests!D1'
        workbook.active = workbook['Postings']
        workbook.views[0].firstSheet = workbook.index(workbook['Requests'])
        latest.defined_names.add(DefinedName('LatestRoster', attr_text=f"'{LATEST}'!$D$3"))
        workbook['Requests'].defined_names.add(DefinedName('RequestHeading', attr_text="'Requests'!$D$1"))
        postings = workbook['Postings']
        options = (
            ('R1', 'IMH', 'Inpatient Psychiatry', 6), ('R2', 'SGH', 'Geriatric Psychiatry', 3),
            ('R2', 'IMH', 'Child & Adolescent Psychiatry', 3), ('R3', 'NUH', 'Continuity Clinic', 12),
            ('R4', 'IMH', 'Inpatient Psychiatry', 3), ('R4', 'KTPH', 'Consultation Liaison Psychiatry', 3),
            ('R4', 'IMH', 'Emergency Psychiatry', 3), ('R4', 'IMH', 'Forensic Psychiatry', 3),
        )
        for year, site, name, duration in options:
            postings.append([year, 'Core', site, name, duration, duration, name])

        def resident(sheet, row, name, mcr, year, intake, labels):
            for col, value in enumerate([intake, None, None, name, mcr, year, *labels], 1):
                sheet.cell(row, col).value = value

        resident(latest, 3, 'Edited Resident', 'M101A', 'R1', 2027, [MEDICINE] * 6 + [INPATIENT] * 5 + [None])
        latest['B3'], latest['C3'] = 'MOM-101', 'resident@example.com'
        latest['S3'] = 'Old remarks'
        resident(latest, 4, 'Resident on LOA', 'M102A', 'R1', 2027, [MEDICINE] * 6 + [INPATIENT] * 5 + ['LOA'])
        resident(latest, 5, 'Resident 1', None, 'R1', 2026, [None] * 12)
        resident(latest, 6, 'Graduating Resident', 'M105A', 'R5', 2023,
                 ['IMH Child and Geriatric Psychiatry'] * 6 + ['IMH General Psychiatry (Elective)'] * 6)
        resident(latest, 7, 'Unclear Resident', 'M103A', 'R5', 2024, ['Unmapped history'] + [None] * 11)
        latest.merge_cells('G7:R7')
        resident(latest, 8, 'Resident on full-year LOA', 'M104A', 'R1', 2027, ['LOA'] * 12)
        labels = [
            [MEDICINE] * 6 + [INPATIENT] * 6,
            ['SGH Geriatric Psychiatry'] * 3 + ['IMH Child & Adolescent Psychiatry'] * 3
            + ['IMH Addiction Medicine'] * 3 + ['IMH Addiction Medicine (Elective)'] * 3,
            ['NUH Continuity Clinic'] * 12,
            [INPATIENT] * 3 + ['KTPH Consultation Liaison Psychiatry'] * 3
            + ['IMH Emergency Psychiatry'] * 3 + ['IMH Forensic Psychiatry'] * 3,
        ]
        for start, labels_for_year in enumerate(labels, 2023):
            historical = workbook.create_sheet(f'Jul {start} - Jun {start + 1}')
            for i in range(12):
                historical.cell(1, 7 + i, datetime(start + (i + 6) // 12, (i + 6) % 12 + 1, 1))
            for i, label in enumerate((None, None, None, 'Name', 'MCR No.', 'Residency Year'), 1):
                historical.cell(2, i, label)
            resident(historical, 3, 'Graduating Resident', 'M105A', f'R{start - 2022}', 2023, labels_for_year)
        if next_sheet:
            workbook.create_sheet(NEXT)['A1'] = 'A worksheet that must never be replaced'

    return structured_workbook_bytes(populate)


def edited_draft(content):
    workbook = parse_workbook(content)
    resident = workbook['residents'][0]
    target = next(option for option in posting_catalogue(workbook['postings'])
                  if option['residency_year'] == 'R1' and option['label'] == INPATIENT)
    months = [{'month': month['month'], 'status': 'outside_draft_scope'} for month in workbook['months']]
    months[-1].update(status='posting', target=target, label=INPATIENT)
    return {'status': 'edited', 'cutoff': '2027-06', 'residents': [
        {**{key: resident[key] for key in ('name', 'mcr', 'source')}, 'projected_year': 'R1', 'months': months}]}


class WorkbookRolloverTests(unittest.TestCase):
    def test_edited_draft_round_trips_with_clean_roster_and_preserved_history(self):
        comments_path = 'xl/comments/comment2.xml'
        drawing_path = 'xl/drawings/commentsDrawing2.vml'
        control = (b'<v:shape xmlns:v="urn:schemas-microsoft-com:vml" id="request-button">'
                   b'<x:ClientData xmlns:x="urn:schemas-microsoft-com:office:excel" ObjectType="Button">'
                   b'<x:Row>2</x:Row><x:Column>3</x:Column></x:ClientData></v:shape>')
        with_control = BytesIO()
        with ZipFile(BytesIO(fixture(request_notes=True))) as source, ZipFile(with_control, 'w') as target:
            for entry in source.infolist():
                data = source.read(entry)
                if entry.filename == drawing_path:
                    data = data.replace(b'</xml>', control + b'</xml>')
                target.writestr(entry, data)
        content = with_control.getvalue()
        draft = edited_draft(content)
        normal_export, _ = export_workbook(content, 2027, draft)
        output, year, warnings = prepare_next_workbook(content, STORE, draft, target_year=2028)
        self.assertEqual(year, 2028)
        self.assertEqual(warnings['anonymous_slots'], [5])
        self.assertEqual(warnings['unresolved_progress'], [7])
        self.assertNotIn(8, warnings.get('missing_latest_progress', []))
        with ZipFile(BytesIO(normal_export)) as old, ZipFile(BytesIO(output)) as new:
            changed = {'[Content_Types].xml', 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels',
                       'xl/styles.xml', 'xl/worksheets/sheet2.xml', comments_path, drawing_path}
            for name in old.namelist():
                if name not in changed:
                    self.assertEqual(new.read(name), old.read(name), name)
            self.assertIn(control, new.read(drawing_path))
            self.assertEqual(new.read(drawing_path).count(b'ObjectType="Note"'), 2)

        workbook = load_workbook(BytesIO(output))
        before = load_workbook(BytesIO(normal_export))
        position = before.sheetnames.index(LATEST) + 1
        self.assertEqual(workbook.sheetnames, before.sheetnames[:position] + [NEXT] + before.sheetnames[position:])
        self.assertEqual(workbook.active.title, 'Postings')
        self.assertEqual(workbook.sheetnames[workbook.views[0].firstSheet], 'Requests')
        latest, following, requests = workbook[LATEST], workbook[NEXT], workbook['Requests']
        self.assertEqual(latest.defined_names['LatestRoster'].attr_text, f"'{LATEST}'!$D$3")
        self.assertEqual(requests.defined_names['RequestHeading'].attr_text, "'Requests'!$D$1")
        self.assertEqual(latest['R3'].value, INPATIENT)
        self.assertEqual(latest['D3'].comment.text, 'Existing note')
        self.assertEqual(requests['D1'].value, 'Posting Request')
        self.assertEqual(requests['D1'].comment.text, 'Request heading')
        self.assertIsNone(requests['D2'].value)
        self.assertIsNone(requests['D3'].value)
        self.assertIsNone(requests['D3'].comment)
        self.assertIsNone(requests['D4'].value)
        self.assertIsNone(requests['D4'].comment)
        self.assertTrue(requests['D3'].alignment.wrap_text)
        self.assertEqual(requests['J3'].value, 'Keep layout note outside request fields')
        self.assertEqual(requests['J3'].comment.text, 'Layout note')
        self.assertEqual(requests.freeze_panes, 'D2')
        self.assertEqual(following.freeze_panes, 'G3')
        self.assertEqual(following.column_dimensions['D'].width, 31)
        self.assertEqual(following.row_dimensions[3].height, 23)
        self.assertEqual(list(map(str, following.merged_cells.ranges)), ['S1:S2'])
        self.assertEqual(following['G1'].value, datetime(2028, 7, 1))
        self.assertEqual(following['R1'].value, datetime(2029, 6, 1))
        self.assertEqual(following['G2'].value, 'Jul 2028')
        self.assertEqual(following['R2'].value, 'Jun 2029')
        self.assertTrue(following['D3'].font.bold)
        self.assertEqual(following['D3'].font.name, 'Arial')
        self.assertIsNone(following['D3'].font.color)
        self.assertIsNone(following['D3'].comment)
        self.assertIsNone(following['G3'].fill.patternType)
        self.assertEqual(following['H3'].fill.fgColor.rgb[-6:], 'DDEEFF')
        self.assertTrue(following['J3'].alignment.wrap_text)
        self.assertIsNone(following['S3'].value)
        self.assertEqual((following['B3'].value, following['C3'].value), ('MOM-101', 'resident@example.com'))

        imported = parse_workbook(output)
        self.assertEqual(imported['target_year'], 2028)
        self.assertEqual(imported['requests'], [])
        residents = imported['residents']
        self.assertEqual([(r['name'], r['residency_year']) for r in residents[:4]],
                         [('Edited Resident', 'R2'), ('Resident on LOA', 'R1'), ('Unclear Resident', 'R5'),
                          ('Resident on full-year LOA', 'R1')])
        self.assertEqual([r['name'] for r in residents[4:]], [f'Resident {i}' for i in range(1, 25)])
        self.assertTrue(all(r['intake'] == '2028' and r['mcr'] is None and r['residency_year'] == 'R1' and r['slot_id']
                            for r in residents[4:]))
        self.assertTrue(all(month['status'] == 'blank' for r in residents for month in r['postings']))
        self.assertEqual(imported['incoming_intake']['placeholder_count'], 24)

    def test_endpoint_uses_latest_worksheet_without_draft_and_checks_target_year(self):
        client = TestClient(app)
        content = fixture()
        fields = {'target_year': 2028, 'store': STORE.model_dump_json()}
        response = client.post('/api/export/prepare-next-year', data=fields, files={'originalFile': ('Roster.xlsx', content)})
        self.assertEqual(response.status_code, 200, response.text[:300] if response.status_code != 200 else '')
        self.assertIn('Prepared%202028-2029.xlsx', response.headers['Content-Disposition'])
        self.assertEqual(json.loads(response.headers['X-Preparation-Review'])['anonymous_slots'], [5])
        self.assertEqual(parse_workbook(response.content)['residents'][0]['residency_year'], 'R1')
        self.assertIsNone(load_workbook(BytesIO(response.content))[LATEST]['R3'].value)
        for existing in (fixture(next_sheet=True), response.content):
            with self.subTest(size=len(existing)), self.assertRaisesRegex(WorkbookError, 'already exists'):
                prepare_next_workbook(existing, STORE, target_year=2028)

    def test_saved_review_credits_the_exact_historical_period_after_reimport(self):
        workbook = load_workbook(BytesIO(fixture()))
        for cell in workbook[LATEST]['G3:L3'][0]:
            cell.value = 'Combined medicine shorthand'
        workbook[LATEST]['R3'] = INPATIENT
        stream = BytesIO()
        workbook.save(stream)
        content = stream.getvalue()
        history = evaluate_review(parse_workbook(content), STORE)
        entry = next(entry for entry in history['entries'] if entry['months'][0]['value'] == 'Combined medicine shorthand')
        candidate = next(candidate for candidate in history['catalogue'] if candidate['label'] == MEDICINE)
        store = ReviewStore.model_validate({'version': 1, 'decisions': [{
            'kind': 'resident', 'context': entry['context'], 'requirement_year': 'R1',
            'target': {key: candidate[key] for key in ('key', 'signature')},
        }]})
        unresolved, _, warnings = prepare_next_workbook(content, STORE, target_year=2028)
        self.assertIn(3, warnings['unresolved_progress'])
        self.assertEqual(parse_workbook(unresolved)['residents'][0]['residency_year'], 'R1')
        resolved, _, warnings = prepare_next_workbook(content, store, target_year=2028)
        self.assertNotIn(3, warnings['unresolved_progress'])
        imported = parse_workbook(resolved)
        self.assertEqual(imported['residents'][0]['residency_year'], 'R2')
        ledger = build_requirement_ledger(imported, store)
        self.assertEqual(ledger['cutoff'], '2028-06')
        self.assertEqual(ledger['residents'][0]['r1_routes'][1]['evidence_status'], 'supported')
