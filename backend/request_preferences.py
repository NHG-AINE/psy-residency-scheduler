"""Resolve request text conservatively against the uploaded catalogue."""
import re
from copy import deepcopy
from math import lcm

if __package__:
    from .workbook_import import normalized_label, normalized_posting_label
    from .rules.r2_rules import partial_posting_identity
    from .rules.r5_rules import elective_durations
    from .rules.r4_rules import completed_r1_inpatient_at_imh
else:
    from workbook_import import normalized_label, normalized_posting_label
    from rules.r2_rules import partial_posting_identity
    from rules.r5_rules import elective_durations
    from rules.r4_rules import completed_r1_inpatient_at_imh

MONTHS = {name: number for number, names in enumerate((('jan','january'), ('feb','february'), ('mar','march'), ('apr','april'), ('may',), ('jun','june'), ('jul','july'), ('aug','august'), ('sep','sept','september'), ('oct','october'), ('nov','november'), ('dec','december')), 1) for name in names}


def period_starts(value, planning_months, duration):
    if value is None or isinstance(value, str) and not value.strip():
        return list(range(len(planning_months)))
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
    # Preserve block-aligned windows; only the planning-year boundary may
    # truncate the requested block. Remaining training carries into next year.
    return [start for start in range(a, b + 1, duration)
            if min(start + duration - 1, len(months) - 1) <= b]


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
        label = normalized_posting_label(raw)
        marker = re.search(r'\s*\((core|elective)\)$', label)
        category_filter = marker[1] if marker else None
        if marker:
            label = label[:marker.start()].rstrip()
        matches = [o for o in options if o.get('valid') and o.get('requirement_id') in requirements and o.get('residency_year') in eligible_years
                   and (category_filter is None or o['category'] == category_filter)
                   and label in {normalized_posting_label(o['label']), normalized_posting_label(o['posting'])}]
        if category_filter is None:
            matches = [o for o in matches if requirements[o['requirement_id']]['remaining_months'] > 0] or matches
            matches = [o for o in matches if o['category'] == 'core'
                       and (o['residency_year'].lower() in person['recorded_years']
                            or requirements[o['requirement_id']]['remaining_months'])] or matches
        current = [o for o in matches if o['residency_year'].lower() in person['recorded_years']]
        if current:
            matches = current
        else:
            matches = [o for o in matches if requirements[o['requirement_id']]['remaining_months']]
        identities = {(o['requirement_id'], normalized_posting_label(o['posting']), o['category']) for o in matches}
        if len(identities) != 1:
            item['reason'] = 'No unique eligible catalogue posting'
            continue
        requirement_id, service, category = next(iter(identities))
        req = requirements[requirement_id]
        duration = req['required_months']
        duration_starts = None
        if requirement_id == 'r5.elective':
            durations = sorted({d for option in matches for d in elective_durations(option)})
            if not durations:
                item['reason'] = 'No unique eligible catalogue posting'
                continue
            duration_starts = {d: period_starts(row.get('period'), planning_months, d) for d in durations}
            duration = min((d for d in durations if duration_starts[d]), default=min(durations))
        starts = period_starts(row.get('period'), planning_months, duration)
        if starts is None:
            item['reason'] = 'Period is unclear or outside the planning year'
            continue
        if duration_starts is not None:
            item['duration_starts'] = duration_starts
            # A requested continuation consumes only its outstanding months.
            # Completed three-month blocks do not discount a fresh request.
            tail, identity = 0, None
            for month in reversed(person.get('months', [])):
                if month['status'] == 'loa':
                    continue
                if month['status'] != 'expected' or month.get('requirement_id') != requirement_id:
                    break
                current = (month['posting'], month['institution'])
                if identity is not None and current != identity:
                    break
                identity = current
                tail += 1
            charges = [d - tail for option in matches if (option['posting'], option['institution']) == identity
                       for d in elective_durations(option) if d > tail and duration_starts.get(d)]
            item['remaining_duration'] = min([duration] + charges)
            starts = sorted({start for values in duration_starts.values() for start in values})
        item.update(status='evaluable', requirement_id=requirement_id, duration=duration, starts=starts,
                    period_months=period_starts(row.get('period'), planning_months, 1),
                    option_keys=sorted({(o['requirement_id'], o['institution'], o['label']) for o in matches}))
    seen = {}
    for item in outcomes:
        if item['status'] != 'evaluable':
            continue
        key = (tuple(item['option_keys']), tuple(item['starts']),
               tuple((d, tuple(starts)) for d, starts in item.get('duration_starts', {}).items()),
               tuple(item['period_months']) if 'duration_starts' in item else ())
        if key in seen:
            item['duplicate_of'] = seen[key]
        else:
            seen[key] = outcomes.index(item)
    for requirement_id, req in requirements.items():
        group = [i for i in outcomes if i['status'] == 'evaluable' and 'duplicate_of' not in i and i['requirement_id'] == requirement_id]
        if req['remaining_months'] and len(group) > 1 and sum(i.get('remaining_duration', i['duration']) for i in group) > req['remaining_months']:
            for item in group:
                item.update(status='pending', reason='Competing requests need clarification')
            for item in outcomes:
                if 'duplicate_of' in item and outcomes[item['duplicate_of']]['status'] == 'pending':
                    item.update(status='pending', reason='Competing requests need clarification')
    return outcomes


def requests_need_r5_split(outcomes):
    """Only resolved requests that call for three-month blocks enable a new split."""
    rows = [row for row in outcomes if row['status'] == 'evaluable' and 'duplicate_of' not in row
            and row.get('requirement_id') == 'r5.elective' and row.get('duration_starts', {}).get(3)]
    for row in rows:
        period = row['request'].get('period')
        if (isinstance(period, str) and period.strip() and len(row['period_months']) < 6
                or 6 not in row['duration_starts']):
            return True
    return False


def placement_fulfils_request(placement, request):
    """Placements already satisfy training rules; a request recognises their start."""
    option = placement['option']
    if request.get('duration_starts') is not None:
        duration = placement.get('block_duration', len(placement['months']) + placement.get('remaining', 0))
        if (duration not in elective_durations(option) or not placement['months']
                or placement['months'][0] not in request['duration_starts'].get(duration, [])
                or any(month not in request['period_months'] for month in placement['months'])):
            return False
    return bool(placement['months']) and (
        option['requirement_id'], option['institution'], option['label']
    ) in request['option_keys'] and placement['months'][0] in request['starts']


def add_request_objective(model, outcomes, placements):
    groups = []
    for i, rows in enumerate(outcomes):
        evaluable = [row for row in rows if row['status'] == 'evaluable' and 'duplicate_of' not in row]
        if not evaluable:
            continue
        for n, row in enumerate(evaluable):
            candidates = [p['variable'] for p in placements[i] if placement_fulfils_request(p, row)]
            flag = model.new_bool_var(f'request_{i}_{n}')
            model.add_max_equality(flag, candidates or [0])
            row['_flag'] = flag
        groups.append(evaluable)
    scale = lcm(*(len(g) for g in groups)) if groups else 1
    return sum((scale // len(g)) * (len(g) - sum(row['_flag'] for row in g)) for g in groups)


def unmet_request_reason(person, request, placements, options, stages):
    """Explain proven individual restrictions; do not infer global conflicts."""
    key = request['requirement_id']
    requirement = next(r for r in person['requirements'] if r['requirement_id'] == key)
    if not requirement['remaining_months']:
        return 'requirement_completed', 'This requirement was already completed before the planning year.'
    requested = [o for o in options if (o['requirement_id'], o['institution'], o['label']) in request['option_keys']]
    if (key == 'r4.inpatient_psychiatry' and requested
            and all(o['institution'] == 'IMH' for o in requested)
            and completed_r1_inpatient_at_imh(person)):
        return 'r1_imh_exclusion', 'R1 Inpatient Psychiatry was completed at IMH. R4 Inpatient must be outside IMH.'
    # R5 elective history can include a completed first block and a different
    # partial second block. Actual placement choices below express continuation.
    partial = partial_posting_identity(person, key) if key != 'r5.elective' else None
    if partial and requested and all((o['posting'], o['institution']) != partial for o in requested):
        posting, institution = partial
        return 'partial_posting_continuation', f'This requirement must continue as {institution} {posting}, where it was started.'
    if requested and all(o.get('capacity') == 0 for o in requested):
        return 'zero_capacity', 'The requested posting has zero capacity in the Postings tab.'
    if not request['starts']:
        duration = request['duration']
        window = len(request['period_months'])
        posting = f"{requirement['requirement_year']} {requirement['posting']}"
        period = request['request']['period']
        return 'no_valid_start', (f"{posting} requires {duration} {'month' if duration == 1 else 'months'}, "
                                 f"but the requested {period} period is only {window} {'month' if window == 1 else 'months'}.")
    # Use the scheduler's actual placement choices, including history and LOA.
    possible = [p for p in placements if p['option'].get('capacity') != 0 and placement_fulfils_request(p, request)]
    if not possible:
        if all(not person['availability'][m]['available'] for m in request['starts']):
            return 'loa_start', 'Recorded LOA prevents the posting from starting on any permitted date in the requested period.'
        matching = [p for p in placements if p['option'].get('capacity') != 0
                    and (p['option']['requirement_id'], p['option']['institution'], p['option']['label']) in request['option_keys']]
        starts = [p['months'][0] for p in matching if p['months']]
        if matching and (not starts or min(starts) > max(request['starts'])):
            return 'training_progression', 'Outstanding training and required block order prevent a start within the requested period.'
        return 'no_valid_placement', "No placement matches this request under the resident's remaining training and timing rules."
    stage = next((s for s in stages if s['priority'] == 'resident_requests'), None)
    if stage is None or stage['status'] != 'optimal':
        return 'request_search_incomplete', 'The search time limit was reached before request optimisation was completed. This request may still be achievable.'
    return 'not_selected', 'This request was not fulfilled in the best overall request allocation found. A specific individual restriction has not been established.'
