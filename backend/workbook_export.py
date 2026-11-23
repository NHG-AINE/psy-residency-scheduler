"""Export by patching the original XLSX parts; unrelated ZIP entries stay intact."""
from copy import deepcopy
from io import BytesIO
import posixpath
import re
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

if __package__:
    from .workbook_import import WorkbookError, header, parse_workbook, posting_catalogue
else:
    from workbook_import import WorkbookError, header, parse_workbook, posting_catalogue

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
DOCREL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
VML = 'urn:schemas-microsoft-com:vml'
EXCEL = 'urn:schemas-microsoft-com:office:excel'


def _ref(source):
    return source.get('sheet'), source.get('row')


def _append(xml, tag, fragment):
    """Insert without reserialising namespaces, extensions or existing objects."""
    closing = rf'</(?:\w+:)?{tag}\s*>'
    if not re.search(closing, xml):
        xml = re.sub(rf'<((?:\w+:)?{tag})\b([^>]*)/>', r'<\1\2></\1>', xml, count=1)
    if not re.search(closing, xml):
        raise WorkbookError(f'Missing workbook XML container: {tag}.')
    return re.sub(closing, lambda m: fragment + m[0], xml, count=1)


def _text_cell(coord, value, style=None):
    attributes = f' r={quoteattr(coord)}' + (f' s={quoteattr(str(style))}' if style is not None else '')
    return f'<c{attributes} t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'


def _set_cell(xml, coord, value=None, style=None):
    pattern = rf'<(?:\w+:)?c\b(?=[^>]*\br="{coord}")[^>]*?(?:/>|>.*?</(?:\w+:)?c>)'
    match = re.search(pattern, xml, re.DOTALL)
    if value is None:
        if not match:
            raise WorkbookError('The resident name cell is missing.')
        cell = re.sub(r'\s+s="[^"]*"', '', match[0], count=1)
        cell = re.sub(r'(<(?:\w+:)?c)\b', rf'\1 s="{style}"', cell, count=1)
    else:
        if style is None and match:
            old_style = re.search(r'\bs="([^"]*)"', match[0])
            style = old_style[1] if old_style else None
        cell = _text_cell(coord, value, style)
    if match:
        return xml[:match.start()] + cell + xml[match.end():]
    row_number = re.search(r'\d+$', coord)[0]
    row = re.search(rf'<(?:\w+:)?row\b(?=[^>]*\br="{row_number}")[^>]*>.*?</(?:\w+:)?row>', xml, re.DOTALL)
    if not row:
        raise WorkbookError('The resident row is missing.')
    # Keep cells in column order, including when an original blank cell was absent.
    column = column_index_from_string(re.match(r'[A-Z]+', coord)[0])
    later = next((m for m in re.finditer(r'<(?:\w+:)?c\b[^>]*\br="([A-Z]+)\d+"', row[0])
                  if column_index_from_string(m[1]) > column), None)
    position = row.start() + (later.start() if later else row[0].rfind('</'))
    return xml[:position] + cell + xml[position:]


def _red_style(styles, style_id):
    root = ET.fromstring(styles)
    fonts, xfs = root.find(f'{{{MAIN}}}fonts'), root.find(f'{{{MAIN}}}cellXfs')
    xf = deepcopy(xfs[style_id])
    font = deepcopy(fonts[int(xf.get('fontId', '0'))])
    for color in list(font.findall(f'{{{MAIN}}}color')):
        font.remove(color)
    ET.SubElement(font, f'{{{MAIN}}}color', rgb='FFFF0000')
    xf.set('fontId', str(len(fonts)))
    xf.set('applyFont', '1')
    ET.register_namespace('', MAIN)
    for tag, node, count in [('fonts', font, len(fonts) + 1), ('cellXfs', xf, len(xfs) + 1)]:
        styles = _append(styles, tag, ET.tostring(node, encoding='unicode'))
        styles = re.sub(rf'(<{tag}\b[^>]*\bcount=")[^"]*', rf'\g<1>{count}', styles, count=1)
    return styles, len(xfs)


def _notes(person):
    result = []
    unmet = False
    for outcome in person.get('requests', []):
        if 'duplicate_of' in outcome or outcome.get('status') == 'met':
            continue
        alternatives = outcome.get('alternatives') or [outcome]
        if any(row.get('status') == 'met' for row in alternatives):
            continue
        status = outcome.get('status')
        if status not in {'not_met', 'pending'}:
            raise WorkbookError('Invalid request outcome.')
        unmet |= status == 'not_met'
        requested = ' OR '.join(f"{row['request'].get('posting_request') or '(unspecified)'} ({row['request'].get('period') or 'Any time in planning year'})" for row in alternatives)
        assigned = '; '.join(f"{row['label']} ({', '.join(row['months'])})" for row in outcome.get('assigned', [])) or 'No matching assignment'
        result.append(f"Request {'not met' if status == 'not_met' else 'pending review'}: {requested}\nAssigned: {assigned}\nReason: {outcome.get('reason') or 'Requires staff review.'}")
    completed = [m['month'] for m in person['months'] if m['status'] == 'requirements_completed']
    if completed:
        result.append(f"Draft projection: requirements completed; unallocated months remain blank ({', '.join(completed)}).")
    return '\n\n'.join(result), unmet


def _add_notes(parts, sheet_path, sheet_xml, notes):
    if not notes:
        return sheet_xml
    rel_path = posixpath.join(posixpath.dirname(sheet_path), '_rels', posixpath.basename(sheet_path) + '.rels')
    rel_xml = parts.get(rel_path, f'<Relationships xmlns="{REL}"></Relationships>')
    relationships = ET.fromstring(rel_xml)
    def existing(kind):
        return next((r for r in relationships if r.get('Type', '').endswith('/' + kind)), None)
    def path(rel):
        return posixpath.normpath(posixpath.join(posixpath.dirname(sheet_path), rel.get('Target').lstrip('/'))) if not rel.get('Target').startswith('/') else rel.get('Target').lstrip('/')
    def add(kind, target):
        nonlocal rel_xml
        used = {r.get('Id') for r in ET.fromstring(rel_xml)}
        rid = next(f'rId{i}' for i in range(1, len(used) + 2) if f'rId{i}' not in used)
        fragment = f'<Relationship Id="{rid}" Type="{DOCREL}/{kind}" Target={quoteattr(posixpath.relpath(target, posixpath.dirname(sheet_path)))}/>'
        rel_xml = _append(rel_xml, 'Relationships', fragment)
        return rid
    comment_rel, vml_rel = existing('comments'), existing('vmlDrawing')
    threaded_rel = existing('threadedComment')
    if threaded_rel is not None:
        threaded_path = path(threaded_rel)
        threaded = parts[threaded_path]
        for coord, note in notes.items():
            pattern = rf'<(?:\w+:)?threadedComment\b(?=[^>]*\bref="{coord}")[^>]*>.*?</(?:\w+:)?threadedComment>'
            match = re.search(pattern, threaded, re.DOTALL)
            if match:
                replacement = _append(match[0], 'text', escape('\n\nDraft export\n' + note))
                threaded = threaded[:match.start()] + replacement + threaded[match.end():]
        parts[threaded_path] = threaded
    # New part names avoid collisions with any workbook objects already present.
    def fresh(directory, suffix):
        return next(f'xl/{directory}/draft{i}.{suffix}' for i in range(1, 2002) if f'xl/{directory}/draft{i}.{suffix}' not in parts)
    comment_path = path(comment_rel) if comment_rel is not None else fresh('comments', 'xml')
    vml_path = path(vml_rel) if vml_rel is not None else fresh('drawings', 'vml')
    comments = parts.get(comment_path, f'<comments xmlns="{MAIN}"><authors><author>PSY Scheduler</author></authors><commentList></commentList></comments>')
    root = ET.fromstring(comments)
    authors = root.find(f'{{{MAIN}}}authors')
    author_id = len(authors)
    comments = _append(comments, 'authors', '<author>PSY Scheduler</author>')
    existing_notes = {c.get('ref'): c for c in root.find(f'{{{MAIN}}}commentList')}
    vml = parts.get(vml_path, '<xml></xml>')
    if '_x0000_t202' not in vml:
        vml = _append(vml, 'xml', f'<v:shapetype xmlns:v="{VML}" id="_x0000_t202" coordsize="21600,21600"/>')
    shape_id = max([1025, *[int(n) for n in re.findall(r'_x0000_s(\d+)', vml)]])
    for coord, note in notes.items():
        if coord in existing_notes:
            # Retain rich original note runs and append plain text to their text node.
            pattern = rf'<(?:\w+:)?comment\b(?=[^>]*\bref="{coord}")[^>]*>.*?</(?:\w+:)?comment>'
            match = re.search(pattern, comments, re.DOTALL)
            added = escape(chr(10) + chr(10) + note)
            if re.search(r'<(?:\w+:)?r\b', match[0]):
                replacement = _append(match[0], 'text', f'<r><t xml:space="preserve">{added}</t></r>')
            elif re.search(r'<(?:\w+:)?t\b', match[0]):
                replacement = _append(match[0], 't', added)
            else:
                replacement = _append(match[0], 'text', f'<t xml:space="preserve">{added}</t>')
            comments = comments[:match.start()] + replacement + comments[match.end():]
        else:
            comments = _append(comments, 'commentList', f'<comment ref="{coord}" authorId="{author_id}"><text><t xml:space="preserve">{escape(note)}</t></text></comment>')
            shape_id += 1
            row = int(re.search(r'\d+$', coord)[0]) - 1
            col = column_index_from_string(re.match(r'[A-Z]+', coord)[0]) - 1
            vml = _append(vml, 'xml', f'<v:shape xmlns:v="{VML}" xmlns:x="{EXCEL}" id="_x0000_s{shape_id}" type="#_x0000_t202" style="position:absolute;width:360pt;height:160pt;visibility:hidden" fillcolor="#ffffe1"><v:fill color2="#ffffe1"/><v:shadow on="t" color="black" obscured="t"/><v:path/><v:textbox><div style="text-align:left"/></v:textbox><x:ClientData ObjectType="Note"><x:MoveWithCells/><x:SizeWithCells/><x:AutoFill>False</x:AutoFill><x:Row>{row}</x:Row><x:Column>{col}</x:Column></x:ClientData></v:shape>')
    if comment_rel is None:
        add('comments', comment_path)
        parts['[Content_Types].xml'] = _append(parts['[Content_Types].xml'], 'Types', f'<Override PartName="/{comment_path}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/>')
    if vml_rel is None:
        rid = add('vmlDrawing', vml_path)
        drawing = f'<legacyDrawing xmlns:r="{DOCREL}" r:id="{rid}"/>'
        later = re.search(r'<(?:\w+:)?(?:legacyDrawingHF|picture|oleObjects|controls|webPublishItems|tableParts|extLst)\b', sheet_xml)
        sheet_xml = sheet_xml[:later.start()] + drawing + sheet_xml[later.start():] if later else _append(sheet_xml, 'worksheet', drawing)
        if not any(e.get('Extension') == 'vml' for e in ET.fromstring(parts['[Content_Types].xml'])):
            parts['[Content_Types].xml'] = _append(parts['[Content_Types].xml'], 'Types', '<Default Extension="vml" ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/>')
    parts[comment_path], parts[vml_path], parts[rel_path] = comments, vml, rel_xml
    return sheet_xml


def export_workbook(content, target_year, draft):
    workbook = parse_workbook(content)
    if target_year != workbook['target_year'] or draft.get('status') not in {'optimal', 'feasible', 'edited'} or draft.get('cutoff') != f'{target_year}-06':
        raise WorkbookError('Export requires a completed draft for the latest planning year.')
    original = load_workbook(BytesIO(content), data_only=False, keep_links=True)
    try:
        sheet = original[workbook['target_sheet']]
        _, columns = header(sheet, {'name', 'mcr no.', 'residency year'})
        residents = {_ref(r['source']): r for r in workbook['residents']}
        months = {m['month']: m['source']['column'] for m in workbook['months']}
        catalogue = posting_catalogue(workbook['postings'])
        with ZipFile(BytesIO(content)) as archive:
            # Decode only the parts we patch; preserve binary and unsupported OOXML parts.
            parts = {name: archive.read(name) for name in archive.namelist()}
            book = ET.fromstring(parts['xl/workbook.xml'])
            rels = ET.fromstring(parts['xl/_rels/workbook.xml.rels'])
            rid = next(s.get(f'{{{DOCREL}}}id') for s in book.find(f'{{{MAIN}}}sheets') if s.get('name') == sheet.title)
            target = next(r.get('Target') for r in rels if r.get('Id') == rid)
            sheet_path = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            xml = parts[sheet_path].decode('utf-8')
            styles = parts['xl/styles.xml'].decode('utf-8')
            notes, seen, unmerged, retained = {}, set(), set(), []
            for person in draft['residents']:
                identity = _ref(person['source'])
                if identity not in residents or identity in seen:
                    raise WorkbookError('Draft resident references do not match the uploaded workbook.')
                seen.add(identity)
                resident = residents[identity]
                if any(person.get(k) != resident.get(k) for k in ('name', 'mcr')):
                    raise WorkbookError('Draft resident identity does not match the uploaded workbook.')
                row = identity[1]
                if len(person['months']) != 12 or {m['month'] for m in person['months']} != months.keys():
                    raise WorkbookError('Draft months do not match the uploaded planning year.')
                preserve_row = False
                for month in person['months']:
                    if month['status'] not in {'posting', 'loa', 'outside_draft_scope', 'requirements_completed'}:
                        raise WorkbookError('Invalid draft month status.')
                    old = next(m for m in resident['postings'] if m['month'] == month['month'])
                    if month['status'] != 'posting' or old['status'] == 'loa':
                        continue
                    target = month.get('target') or {}
                    if not any(o['source'] == target.get('source') and o['category'] == target.get('category')
                               and o['residency_year'] == target.get('residency_year') and o['label'] == month.get('label') for o in catalogue):
                        raise WorkbookError('Draft posting references do not match the workbook catalogue.')
                    coord = f"{months[month['month']]}{row}"
                    for merged in sheet.merged_cells.ranges:
                        if coord not in merged:
                            continue
                        if (merged.min_row != row or merged.max_row != row
                                or not all(get_column_letter(c) in months.values() for c in range(merged.min_col, merged.max_col + 1))):
                            raise WorkbookError('A generated posting overlaps an unsupported merged range.')
                        if sheet.cell(merged.min_row, merged.min_col).value is not None:
                            preserve_row = True
                if preserve_row:
                    retained.append(resident.get('name') or resident.get('mcr') or f'Row {row}')
                    continue
                projected = person.get('projected_year')
                if projected is not None:
                    if not isinstance(projected, str) or not re.fullmatch(r'R[1-5](?:,\s*R[1-5])*', projected):
                        raise WorkbookError('Invalid projected residency year.')
                    xml = _set_cell(xml, f"{get_column_letter(columns['residency year'])}{row}", projected)
                for month in person['months']:
                    if month['status'] not in {'posting', 'loa', 'outside_draft_scope', 'requirements_completed'}:
                        raise WorkbookError('Invalid draft month status.')
                    coord = f"{months[month['month']]}{row}"
                    old = next(m for m in resident['postings'] if m['month'] == month['month'])
                    if month['status'] != 'posting' or old['status'] == 'loa':
                        continue
                    inherited_style = None
                    for merged in sheet.merged_cells.ranges:
                        if coord not in merged:
                            continue
                        anchor = sheet.cell(merged.min_row, merged.min_col)
                        if (anchor.value is not None or merged.min_row != row or merged.max_row != row
                                or not all(get_column_letter(c) in months.values() for c in range(merged.min_col, merged.max_col + 1))):
                            raise WorkbookError('A generated posting overlaps a preserved merged note.')
                        if sheet[coord].style_id == 0:
                            inherited_style = anchor.style_id
                        if str(merged) not in unmerged:
                            xml = re.sub(rf'<(?:\w+:)?mergeCell\b(?=[^>]*\bref="{merged}")[^>]*/>', '', xml, count=1)
                            unmerged.add(str(merged))
                    target = month.get('target') or {}
                    option = next((o for o in catalogue if o['source'] == target.get('source') and o['category'] == target.get('category') and o['residency_year'] == target.get('residency_year') and o['label'] == month.get('label')), None)
                    if option is None:
                        raise WorkbookError('Draft posting references do not match the workbook catalogue.')
                    label = option['label'] + (' (Elective)' if option['category'] == 'elective' else '')
                    xml = _set_cell(xml, coord, label, style=inherited_style)
                note, unmet = _notes(person)
                coord = f"{get_column_letter(columns['name'])}{row}"
                if note:
                    notes[coord] = note
                if unmet:
                    styles, red = _red_style(styles, sheet[coord].style_id)
                    xml = _set_cell(xml, coord, style=red)
            if unmerged:
                count = len(sheet.merged_cells.ranges) - len(unmerged)
                xml = re.sub(r'(<(?:\w+:)?mergeCells\b[^>]*\bcount=")[^"]*', rf'\g<1>{count}', xml, count=1)
                if count == 0:
                    xml = re.sub(r'<(?:\w+:)?mergeCells\b[^>]*>\s*</(?:\w+:)?mergeCells>', '', xml)
            # The parts dictionary stays bytes except for the handful of XML parts changed here.
            touched = {sheet_path: xml, 'xl/styles.xml': styles}
            rel_path = posixpath.join(posixpath.dirname(sheet_path), '_rels', posixpath.basename(sheet_path) + '.rels')
            for name in [rel_path, '[Content_Types].xml', *[n for n in parts if n.endswith('.vml') or re.search(r'/comments[^/]*\.xml$', n) or '/comments/' in n or '/threadedComments/' in n]]:
                if name in parts:
                    touched[name] = parts[name].decode('utf-8')
            before = {name: parts[name].decode('utf-8') for name in touched if name in parts}
            touched[sheet_path] = _add_notes(touched, sheet_path, xml, notes)
            output = BytesIO()
            with ZipFile(output, 'w') as result:
                for info in archive.infolist():
                    value = touched.get(info.filename)
                    result.writestr(info, value.encode('utf-8') if value is not None and value != before.get(info.filename) else parts[info.filename])
                for name in touched.keys() - parts.keys():
                    result.writestr(name, touched[name].encode('utf-8'))
            return output.getvalue(), retained
    finally:
        original.close()
