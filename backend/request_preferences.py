"""Resolve request text conservatively against the uploaded catalogue."""
import re
from copy import deepcopy
from math import lcm

if __package__:
    from .workbook_import import normalized_label
else:
    from workbook_import import normalized_label

MONTHS = {name: number for number, names in enumerate((('jan','january'), ('feb','february'), ('mar','march'), ('apr','april'), ('may',), ('jun','june'), ('jul','july'), ('aug','august'), ('sep','sept','september'), ('oct','october'), ('nov','november'), ('dec','december')), 1) for name in names}


def period_starts(value, planning_months, duration):
    if value is None or isinstance(value, str) and not value.strip():
        return list(range(len(planning_months) - duration + 1))
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'\s*([A-Za-z]+)(?:\s+(\d{4}))?\s*[-\u2013]\s*([A-Za-z]+)\s+(\d{4})\s*', value)
    if not match or match[1].casefold() not in MONTHS or match[3].casefold() not in MONTHS:
        return None
    first, last, end_year = MONTHS[match[1].casefold()], MONTHS[match[3].casefold()], int(match[4])
    start_year = int(match[2]) if match[2] else end_year
    start = f'{start_year:04d}-{first:02d}'
    end = f'{end_year:04d}-{last:02d}'
    months = [m['month'] for m in planning_months]
    if start not in months or end not in months:
        return None
    a, b = months.index(start), months.index(end)
    if b < a:
        return None
    return list(range(a, b - duration + 2, duration))


def resolve_requests(person, requests, options, planning_months):
    """Keep original rows; duplicates share one score and one outcome."""
    requirements = {r['requirement_id']: r for r in person['requirements'] if r['requirement_year'] != 'R1'}
    eligible_years = {f'R{year}' for year in range(2, max((int(year[1:]) for year in person['recorded_years']), default=1) + 1)}
    outcomes = []
    for row in requests:
        if row.get('matched_resident_source') != person['source'] or not row.get('posting_request'):
            continue
        raw = row['posting_request']
        item = {'request': deepcopy(row), 'status': 'pending', 'reason': None}
        outcomes.append(item)
        if not isinstance(raw, str):
            item['reason'] = 'Request must be text'
            continue
        label = normalized_label(raw)
        marker = re.search(r'\s*\((core|elective)\)$', label)
        category_filter = marker[1] if marker else 'core'
        if marker:
            label = label[:marker.start()].rstrip()
        matches = [o for o in options if o.get('valid') and o.get('requirement_id') in requirements and o.get('residency_year') in eligible_years
                   and o['category'] == category_filter
                   and label in {normalized_label(o['label']), normalized_label(o['posting'])}]
        current = [o for o in matches if o['residency_year'].lower() in person['recorded_years']]
        if current:
            matches = current
        else:
            matches = [o for o in matches if requirements[o['requirement_id']]['remaining_months']]
        identities = {(o['requirement_id'], normalized_label(o['posting']), o['category']) for o in matches}
        if len(identities) != 1:
            item['reason'] = 'No unique eligible catalogue posting'
            continue
        requirement_id, service, category = next(iter(identities))
        req = requirements[requirement_id]
        duration = req['required_months']
        starts = period_starts(row.get('period'), planning_months, duration)
        if starts is None:
            item['reason'] = 'Period is unclear or outside the planning year'
            continue
        item.update(status='evaluable', requirement_id=requirement_id, duration=duration, starts=starts,
                    option_keys=sorted({(o['requirement_id'], o['institution'], o['label']) for o in matches}))
    seen = {}
    for item in outcomes:
        if item['status'] != 'evaluable':
            continue
        key = (tuple(item['option_keys']), tuple(item['starts']))
        if key in seen:
            item['duplicate_of'] = seen[key]
        else:
            seen[key] = outcomes.index(item)
    for requirement_id, req in requirements.items():
        group = [i for i in outcomes if i['status'] == 'evaluable' and 'duplicate_of' not in i and i['requirement_id'] == requirement_id]
        if req['remaining_months'] and len(group) > 1 and sum(i['duration'] for i in group) > req['remaining_months']:
            for item in group:
                item.update(status='pending', reason='Competing requests need clarification')
            for item in outcomes:
                if 'duplicate_of' in item and outcomes[item['duplicate_of']]['status'] == 'pending':
                    item.update(status='pending', reason='Competing requests need clarification')
    return outcomes


def add_request_objective(model, outcomes, placements):
    groups = []
    for i, rows in enumerate(outcomes):
        evaluable = [row for row in rows if row['status'] == 'evaluable' and 'duplicate_of' not in row]
        if not evaluable:
            continue
        for n, row in enumerate(evaluable):
            candidates = [p['variable'] for p in placements[i]
                          if (p['option']['requirement_id'], p['option']['institution'], p['option']['label']) in row['option_keys']
                          and len(p['months']) == row['duration'] and not p['remaining']
                          and p['months'] == list(range(p['months'][0], p['months'][0] + row['duration']))
                          and p['months'][0] in row['starts']]
            flag = model.new_bool_var(f'request_{i}_{n}')
            model.add(flag == sum(candidates))
            row['_flag'] = flag
        groups.append(evaluable)
    scale = lcm(*(len(g) for g in groups)) if groups else 1
    return sum((scale // len(g)) * (len(g) - sum(row['_flag'] for row in g)) for g in groups)
