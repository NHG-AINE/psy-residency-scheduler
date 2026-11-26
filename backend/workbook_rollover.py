"""Prepare another planning year in a copy of the uploaded XLSX package."""
from collections import defaultdict
from colorsys import rgb_to_hsv
from copy import deepcopy
from datetime import date
from io import BytesIO
import posixpath
import re
from xml.dom import minidom
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import load_workbook
from openpyxl.styles.colors import COLOR_INDEX
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string, get_column_letter, range_boundaries
from openpyxl.utils.datetime import to_excel

if __package__:
    from .requirement_ledger import build_requirement_ledger, programme_requirements_completed
    from .workbook_export import DOCREL, EXCEL, MAIN, MONTH_ABBREVIATIONS, VML, _append, _append_style, export_workbook, worksheet_path
    from .workbook_import import IDENTITY_FIELDS, WorkbookError, header, normalized_label, parse_workbook, recorded_years, required_sheet
else:
    from requirement_ledger import build_requirement_ledger, programme_requirements_completed
    from workbook_export import DOCREL, EXCEL, MAIN, MONTH_ABBREVIATIONS, VML, _append, _append_style, export_workbook, worksheet_path
    from workbook_import import IDENTITY_FIELDS, WorkbookError, header, normalized_label, parse_workbook, recorded_years, required_sheet


def _tag(name):
    return f'{{{MAIN}}}{name}'


def _next_roster(workbook, year, store, retained):
    next_july = {**workbook, 'target_year': year, 'months': [{'month': f'{year}-07'}]}
    ledger = build_requirement_ledger(next_july, store)
    roster, vacancies, warnings = [], [], defaultdict(list)
    for resident, progress in zip(workbook['residents'], ledger['residents'], strict=True):
        row = resident['source']['row']
        if not normalized_label(resident['mcr']) and re.fullmatch(r'resident [1-9][0-9]*', normalized_label(resident['name'])):
            vacancies.append(row)
            warnings['anonymous_slots'].append(row)
            continue
        years = recorded_years(resident['residency_year'])
        pending = any(month['status'] == 'pending' for month in progress['months'])
        unresolved = not years or pending or bool(progress['warnings'])
        latest_months = [month['status'] for month in progress['months'] if month['month'] >= f'{year - 1}-07']
        if unresolved:
            warnings['unresolved_progress'].append(row)
        elif 'expected' not in latest_months and latest_months.count('loa') != 12:
            warnings['missing_latest_progress'].append(row)
        if (resident['name'] or resident['mcr'] or f'Row {row}') in retained:
            warnings['merged_row_retained'].append(row)

        requirements = progress['requirements']
        completed = {year for year in ('R2', 'R3', 'R4', 'R5') if all(
            not item['remaining_months'] for item in requirements
            if item['requirement_year'] == year and not item.get('alternative'))}
        if any(route['evidence_status'] == 'supported' for route in progress['r1_routes']):
            completed.add('R1')
        if 'R4' in completed and progress['cluster_coverage']['missing']:
            warnings['missing_cluster'].append(row)
        if not unresolved and programme_requirements_completed(progress['months']):
            continue

        next_year = resident['residency_year']
        if years and not unresolved:
            first = int(min(years)[1:])
            outstanding = next((f'R{year}' for year in range(first, 6) if f'R{year}' not in completed), None)
            partial_earlier = {int(item['requirement_year'][1:]) for item in requirements
                               if item['evidence_status'] == 'partial' and not item.get('alternative')
                               and item['requirement_year'] not in completed}
            earlier = min(partial_earlier, default=first)
            if earlier < first:
                warnings['earlier_requirements'].append(row)
                next_year = f'R{earlier},{outstanding or f"R{first}"}'
            else:
                next_year = outstanding or 'R5'
            if any(f'R{year}' not in completed for year in range(1, first)) and earlier >= first:
                warnings['incomplete_history'].append(row)
        roster.append((row, next_year))
    return roster, vacancies, dict(warnings)


class _CleanStyles:
    theme_names = ('lt1', 'dk1', 'lt2', 'dk2', 'accent1', 'accent2', 'accent3',
                   'accent4', 'accent5', 'accent6', 'hlink', 'folHlink')

    def __init__(self, styles, theme):
        self.xml = styles
        root = ET.fromstring(styles)
        self.xfs = root.find(_tag('cellXfs'))
        self.fonts = root.find(_tag('fonts'))
        self.fills = root.find(_tag('fills'))
        scheme = ET.fromstring(theme).find('.//{*}clrScheme') if theme else None
        self.theme = {name: value[0].get('lastClr', value[0].get('val'))
                      for name in self.theme_names
                      if scheme is not None and (value := scheme.find(f'{{*}}{name}')) is not None and len(value)}
        self.cleaned = {}
        self.cleaned_fonts = {}

    def _red(self, color):
        if color is None:
            return False
        rgb = color.get('rgb')
        if (index := int(color.get('indexed', '-1'))) in range(len(COLOR_INDEX)):
            rgb = COLOR_INDEX[index]
        if (index := int(color.get('theme', '-1'))) in range(len(self.theme_names)):
            rgb = self.theme.get(self.theme_names[index])
        if not rgb or not re.fullmatch(r'[\da-fA-F]{6,8}', rgb):
            return False
        rgb = rgb[-6:]
        hue, saturation, _ = rgb_to_hsv(*(int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4)))
        return saturation > .06 and (hue <= .035 or hue >= .965)

    def clean(self, node, attribute='s'):
        original = node.get(attribute)
        if original is None:
            return
        if original not in self.cleaned:
            xf = deepcopy(self.xfs[int(original)])
            fill = self.fills[int(xf.get('fillId', '0'))]
            if any(self._red(color) for color in fill.iter()
                   if color.tag in {_tag('fgColor'), _tag('bgColor'), _tag('color')}):
                xf.set('fillId', '0')
            font_id = int(xf.get('fontId', '0'))
            font = self.fonts[font_id]
            if self._red(font.find(_tag('color'))):
                if font_id not in self.cleaned_fonts:
                    clean_font = deepcopy(font)
                    clean_font.remove(clean_font.find(_tag('color')))
                    self.cleaned_fonts[font_id] = self._index(self.fonts, 'fonts', clean_font)
                xf.set('fontId', str(self.cleaned_fonts[font_id]))
            self.cleaned[original] = str(self._index(self.xfs, 'cellXfs', xf))
        node.set(attribute, self.cleaned[original])

    def _index(self, collection, name, node):
        value = ET.tostring(node)
        for i, old in enumerate(collection):
            if ET.tostring(old) == value:
                return i
        index = len(collection)
        collection.append(node)
        self.xml = _append_style(self.xml, name, node, len(collection))
        return index


def _set_value(cell, value):
    # Keep only coordinate and formatting; discard formulas, cached data and metadata.
    attributes = {k: v for k, v in cell.attrib.items() if k in {'r', 's'}}
    cell.clear()
    cell.attrib.update(attributes)
    if isinstance(value, str):
        cell.set('t', 'inlineStr')
        string = ET.SubElement(cell, _tag('is'))
        ET.SubElement(string, _tag('t'), {'{http://www.w3.org/XML/1998/namespace}space': 'preserve'}).text = value
    elif value is not None:
        ET.SubElement(cell, _tag('v')).text = str(value)


def _worksheet(xml, template, imported, year, epoch, roster, vacancies, styles):
    root = ET.fromstring(xml)
    tags = {_tag(name) for name in ('sheetPr', 'dimension', 'sheetViews', 'sheetFormatPr', 'cols', 'sheetData',
                                     'mergeCells', 'printOptions', 'pageMargins', 'pageSetup')}
    root.attrib.clear()
    for child in list(root):
        if child.tag not in tags:
            root.remove(child)
    for node in root.iter():
        node.attrib.pop(f'{{{DOCREL}}}id', None)
        if node.tag == _tag('sheetView'):
            node.attrib.pop('tabSelected', None)
        if node.tag == _tag('col'):
            styles.clean(node, 'style')

    heading, columns = header(template, {'name', 'mcr no.', 'residency year'})
    intake = columns.get('residency intake')
    if intake is None:
        intake = template.max_column + 1
        if intake > 100:
            raise WorkbookError('The new planning sheet needs a column for Residency Intake.')
    identity_columns = {columns[key] for key in IDENTITY_FIELDS.values() if key != 'remarks' and key in columns}
    month_columns = {column_index_from_string(month['source']['column']) for month in imported['months']}
    data = root.find(_tag('sheetData'))
    rows = {int(row.get('r')): row for row in data}
    original_rows = rows.copy()

    def set_at(row_number, column, value):
        row = rows[row_number]
        coord = f'{get_column_letter(column)}{row_number}'
        cell = next((cell for cell in row if cell.get('r') == coord), None)
        if cell is None:
            cell = ET.SubElement(row, _tag('c'), r=coord)
        _set_value(cell, value)
        row[:] = sorted(row, key=lambda c: column_index_from_string(coordinate_from_string(c.get('r'))[0]))

    if 'residency intake' not in columns:
        set_at(heading, intake, 'Residency Intake')
    for month in imported['months']:
        _, month_number = map(int, month['month'].split('-'))
        calendar_year = year if month_number >= 7 else year + 1
        source = month['source']
        column = column_index_from_string(source['column'])
        set_at(source['row'], column, to_excel(date(calendar_year, month_number, 1), epoch))
        if source['row'] != heading:
            set_at(heading, column, f'{MONTH_ABBREVIATIONS[month_number - 1]} {calendar_year}')

    month_style = {}
    for row in rows.values():
        if int(row.get('r')) <= heading:
            continue
        for cell in row:
            column = column_index_from_string(coordinate_from_string(cell.get('r'))[0])
            if column in month_columns and cell.get('s') is not None:
                month_style.setdefault(column, cell.get('s'))

    last_template = vacancies[-1] if vacancies else next((row for row in rows if row > heading), None)
    slots = [(vacancies[i] if i < len(vacancies) else last_template, 'R1') for i in range(24)]
    data[:] = [row for row in data if int(row.get('r')) <= heading]
    for index, (source, next_year) in enumerate(roster + slots):
        row_number = heading + index + 1
        slot = index - len(roster) + 1
        original = original_rows.get(source)
        row = deepcopy(original) if original is not None else ET.Element(_tag('row'))
        row.set('r', str(row_number))
        for attribute in ('hidden', 'collapsed', 'outlineLevel', 'spans'):
            row.attrib.pop(attribute, None)
        for cell in row:
            column_letter, _ = coordinate_from_string(cell.get('r'))
            column = column_index_from_string(column_letter)
            cell.set('r', f'{column_letter}{row_number}')
            if slot > 0 or column not in identity_columns or cell.find(_tag('f')) is not None:
                value = template.cell(source, column).value if slot <= 0 and column in identity_columns else None
                _set_value(cell, None if isinstance(value, str) and value.startswith('=') else value)
        rows[row_number] = row
        data.append(row)
        set_at(row_number, columns['residency year'], next_year)
        if slot > 0:
            set_at(row_number, columns['name'], f'Resident {slot}')
            set_at(row_number, intake, year)
        present = {cell.get('r') for cell in row}
        for column, style in month_style.items():
            coord = f'{get_column_letter(column)}{row_number}'
            if coord not in present:
                ET.SubElement(row, _tag('c'), r=coord, s=style)
        row[:] = sorted(row, key=lambda c: column_index_from_string(coordinate_from_string(c.get('r'))[0]))

    for cell in data.iter(_tag('c')):
        styles.clean(cell)
    for row in data:
        styles.clean(row)
    merges = root.find(_tag('mergeCells'))
    if merges is not None:
        merges[:] = [merge for merge in merges if range_boundaries(merge.get('ref'))[3] <= heading]
        if len(merges):
            merges.set('count', str(len(merges)))
        else:
            root.remove(merges)
    dimension = root.find(_tag('dimension'))
    if dimension is not None:
        dimension.set('ref', f'A1:{get_column_letter(max(template.max_column, intake))}{heading + len(roster) + 24}')
    return ET.tostring(root, encoding='utf-8')


def _clear_requests(archive, sheet_path, sheet):
    heading, columns = header(sheet, {'name', 'mcr no.', 'posting request', 'period'})
    fields = set(columns.values())

    def cleared(column, row):
        return column in fields and row > heading

    def clear(match):
        if not cleared(column_index_from_string(match['column']), int(match['row'])):
            return match[0]
        attributes = re.sub(r'\s+(?:t|cm|vm|ph)="[^"]*"', '', match['attributes'])
        return f"<{match['tag']}{attributes}/>"

    xml = archive.read(sheet_path).decode('utf-8')
    touched = {sheet_path: re.sub(
        r'<(?P<tag>(?:\w+:)?c)\b(?P<attributes>[^>]*\br="(?P<column>[A-Z]+)(?P<row>\d+)"[^>]*?)(?:/>|>.*?</(?P=tag)>)',
        clear, xml, flags=re.DOTALL)}
    directory, filename = posixpath.split(sheet_path)
    rel_path = posixpath.join(directory, '_rels', filename + '.rels')
    if rel_path not in archive.namelist():
        return touched

    drawing = ET.fromstring(xml).find(_tag('legacyDrawing'))
    drawing_id = drawing.get(f'{{{DOCREL}}}id') if drawing is not None else None
    for rel in ET.fromstring(archive.read(rel_path)):
        kind = rel.get('Type', '').rsplit('/', 1)[-1]
        if kind != 'comments' and not (kind == 'vmlDrawing' and rel.get('Id') == drawing_id):
            continue
        target = rel.get('Target')
        path = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(directory, target))
        # Keep the original namespace prefixes, including those used by VML controls.
        with minidom.parseString(archive.read(path)) as part:
            removed = False
            if kind == 'comments':
                for note in part.getElementsByTagNameNS(MAIN, 'comment'):
                    column, row = coordinate_from_string(note.getAttribute('ref'))
                    if cleared(column_index_from_string(column), row):
                        note.parentNode.removeChild(note)
                        removed = True
            else:
                for data in part.getElementsByTagNameNS(EXCEL, 'ClientData'):
                    shape = data.parentNode
                    if data.getAttribute('ObjectType') != 'Note' or (shape.namespaceURI, shape.localName) != (VML, 'shape'):
                        continue
                    coords = {node.localName: node.firstChild.nodeValue.strip() for node in data.childNodes
                              if node.namespaceURI == EXCEL and node.localName in {'Row', 'Column'} and node.firstChild}
                    row, column = coords.get('Row', ''), coords.get('Column', '')
                    if row.isdecimal() and column.isdecimal() and cleared(int(column) + 1, int(row) + 1):
                        shape.parentNode.removeChild(shape)
                        removed = True
            if removed:
                touched[path] = part.toxml()
    return touched


def _insert_prepared_sheet(xml, after_index, title, sheet_id, rid):
    prefix = r'(?:[\w.-]+:)?'
    sheets = re.search(rf'<{prefix}sheets\b[^>]*>(.*?)</{prefix}sheets\s*>', xml, re.DOTALL)
    if sheets is None:
        raise WorkbookError('The workbook sheet list could not be updated.')
    entries = list(re.finditer(rf'<{prefix}sheet(?=[\s/>])[^>]*?(?:/>|>\s*</{prefix}sheet\s*>)', sheets[1]))
    if after_index >= len(entries):
        raise WorkbookError('The latest annual worksheet could not be found in the workbook sheet list.')
    position = sheets.start(1) + entries[after_index].end()
    entry = f'<sheet xmlns="{MAIN}" name={quoteattr(title)} sheetId="{sheet_id}" xmlns:r="{DOCREL}" r:id="{rid}"/>'
    xml = xml[:position] + entry + xml[position:]

    def shift_indexes(match):
        def shift(index):
            value = int(index[2])
            return f'{index[1]}{value + 1}{index[3]}' if value > after_index else index[0]

        fields = 'activeTab|firstSheet' if match['tag'] == 'workbookView' else 'localSheetId'
        return re.sub(rf'(\s(?:{fields})\s*=\s*["\'])(\d+)(["\'])', shift, match[0])

    # Excel stores these references by tab position. The existing sheet IDs and
    # relationship IDs are stable, so their references need no adjustment.
    return re.sub(rf'<{prefix}(?P<tag>workbookView|definedName)(?=[\s/>])[^>]*>', shift_indexes, xml)


def prepare_next_workbook(content, store, draft=None, *, target_year=None):
    expected_title = f'Jul {target_year} - Jun {target_year + 1}' if target_year is not None else None
    workbook = parse_workbook(content, forbidden_sheet_title=expected_title)
    year = workbook['target_year'] + 1
    if target_year is not None and target_year != year:
        existing = next((item['sheet'] for item in workbook['available_years'] if item['year'] == target_year), None)
        if existing:
            raise WorkbookError(f'The planning year {target_year} already exists in {existing}. Use the original workbook and retry.')
        raise WorkbookError(f'The latest worksheet is {workbook["target_sheet"]}. Reload the workbook to prepare {year}–{year + 1}.')
    if year >= 9999:
        raise WorkbookError('The next planning year exceeds Excel’s supported dates.')
    title = f'Jul {year} - Jun {year + 1}'
    original = load_workbook(BytesIO(content), data_only=True, keep_links=False)
    try:
        if any(name.casefold() == title.casefold() for name in original.sheetnames):
            raise WorkbookError(f'The worksheet {title} already exists. Rename or remove the conflicting worksheet before retrying.')
        retained = []
        if draft is not None:
            content, retained = export_workbook(content, year - 1, draft)
            workbook = parse_workbook(content)
        roster, vacancies, warnings = _next_roster(workbook, year, store, retained)
        output = BytesIO()
        with ZipFile(BytesIO(content)) as archive, ZipFile(output, 'w', compression=ZIP_DEFLATED) as result:
            book_path, rels_path = 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels'
            styles_path, types_path = 'xl/styles.xml', '[Content_Types].xml'
            book_xml, rels_xml = (archive.read(path).decode('utf-8') for path in (book_path, rels_path))
            book, rels = ET.fromstring(book_xml), ET.fromstring(rels_xml)
            ids = {node.get('Id') for node in rels}
            rid = next(f'rId{i}' for i in range(1, len(ids) + 2) if f'rId{i}' not in ids)
            sheets = book.find(_tag('sheets'))
            sheet_id = 1 + max(int(sheet.get('sheetId')) for sheet in sheets)
            paths = set(archive.namelist())
            sheet_path = next(path for i in range(1, len(paths) + 2) if (path := f'xl/worksheets/prepared{i}.xml') not in paths)
            template = original[workbook['target_sheet']]
            template_index = next(i for i, sheet in enumerate(sheets) if sheet.get('name') == template.title)
            imported = workbook['annual_sheets'][-1]
            raw_sheet = archive.read(worksheet_path(book, rels, template.title))
            styles = _CleanStyles(archive.read(styles_path).decode('utf-8'),
                                  archive.read('xl/theme/theme1.xml') if 'xl/theme/theme1.xml' in paths else None)
            new_sheet = _worksheet(raw_sheet, template, imported, year, original.epoch, roster, vacancies, styles)
            requests = required_sheet(original, 'Requests', 'Request')
            requests_path = worksheet_path(book, rels, requests.title)
            touched = {
                book_path: _insert_prepared_sheet(book_xml, template_index, title, sheet_id, rid),
                rels_path: _append(rels_xml, 'Relationships', f'<Relationship Id="{rid}" Type="{DOCREL}/worksheet" Target="/{sheet_path}"/>'),
                types_path: _append(archive.read(types_path).decode('utf-8'), 'Types',
                                    f'<Override PartName="/{sheet_path}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'),
                styles_path: styles.xml,
                **_clear_requests(archive, requests_path, requests),
            }
            for entry in archive.infolist():
                value = touched.get(entry.filename)
                result.writestr(entry, value.encode('utf-8') if value is not None else archive.read(entry))
            result.writestr(sheet_path, new_sheet)
        return output.getvalue(), year, warnings
    finally:
        original.close()
