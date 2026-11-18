"""Resolve request text conservatively against the uploaded catalogue."""
import re
from copy import deepcopy
from math import lcm

if __package__:
    from .workbook_import import normalized_label, normalized_posting_label
    from .rules.r2_rules import partial_posting_identity
    from .rules.r5_rules import elective_durations
    from .requirement_ledger import R5_CORES, R5_ELECTIVE
    from .programme_requirements import additional_r5_credit
    from .rules.r4_rules import completed_r1_inpatient_at_imh
else:
    from workbook_import import normalized_label, normalized_posting_label
    from rules.r2_rules import partial_posting_identity
    from rules.r5_rules import elective_durations
    from requirement_ledger import R5_CORES, R5_ELECTIVE
    from programme_requirements import additional_r5_credit
    from rules.r4_rules import completed_r1_inpatient_at_imh

MONTHS = {name: number for number, names in enumerate((('jan','january'), ('feb','february'), ('mar','march'), ('apr','april'), ('may',), ('jun','june'), ('jul','july'), ('aug','august'), ('sep','sept','september'), ('oct','october'), ('nov','november'), ('dec','december')), 1) for name in names}


def request_period(value, planning_months):
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
    return list(range(a, b + 1))


def _request_durations(option, required):
    key = option["requirement_id"]
    if key == R5_ELECTIVE:
        return elective_durations(option)
    if key in R5_CORES:
        return (3, 6)
    return (required,)


def resolve_requests(person, requests, options, planning_months):
    """Keep original rows; duplicates share one score and one outcome."""
    requirements = {r['requirement_id']: r for r in person['requirements'] if r['requirement_year'] != 'R1'}
    through = person.get('schedule_through') or max((int(year[1:]) for year in person['recorded_years']), default=1)
    eligible_years = {f'R{year}' for year in range(2, through + 1)}
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
        period = request_period(row.get('period'), planning_months)
        if period is None:
            item['reason'] = 'Period is unclear or outside the planning year'
            continue
        exact = bool((row.get('period') or '').strip())
        lengths = {d for option in matches for d in _request_durations(option, req['required_months'])}
        if not lengths:
            item['reason'] = 'No unique eligible catalogue posting'
            continue
        default = 3 if requirement_id in R5_CORES else 6 if requirement_id == R5_ELECTIVE else req['required_months']
        duration = len(period) if exact else default if default in lengths else min(lengths)
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

        eligible, charges = [], []
        fresh = False
        for option in matches:
            supported = _request_durations(option, req['required_months'])
            credited = tail if (option['posting'], option['institution']) == identity else 0
            if supported == (3,) and 3 < credited < 6:
                credited -= 3  # History contains a full first elective and part of its successor.
            continuation = credited and any(d - credited == duration for d in supported)
            if duration in supported or exact and continuation:
                eligible.append(option)
                fresh |= duration in supported
                credit = additional_r5_credit(option)
                used = credited if not exact and credited < duration else 0
                charges.append(6 - credit["months"] if credit else duration - used)
        item.update(requirement_id=requirement_id, duration=duration, requested_months=duration, exact_period=exact,
                    starts=period[:1] if exact else period, period_months=period,
                    option_keys=sorted({(o['requirement_id'], o['institution'], o['label']) for o in eligible}))
        if not eligible:
            allowed = ' or '.join(map(str, sorted(lengths)))
            months = 'month' if duration == 1 else 'months'
            item.update(status='not_met', reason_code='duration_mismatch',
                        reason=f'{req["requirement_year"]} {req.get("posting") or service} allows {allowed} months. '
                               f'The requested period is {duration} {months}.')
        else:
            item.update(status='evaluable', credit_months=min(charges), fresh_duration=fresh)
    seen = {}
    for item in outcomes:
        if item['status'] != 'evaluable':
            continue
        key = (tuple(item['option_keys']), tuple(item['starts']), item['duration'], item['exact_period'])
        if key in seen:
            item['duplicate_of'] = seen[key]
        else:
            seen[key] = outcomes.index(item)
    for requirement_id, req in requirements.items():
        group = [i for i in outcomes if i['status'] == 'evaluable' and 'duplicate_of' not in i and i['requirement_id'] == requirement_id]
        limit = max([req['remaining_months']] + [i['credit_months'] for i in group]) if requirement_id in R5_CORES else req['remaining_months']
        if limit and len(group) > 1 and sum(i['credit_months'] for i in group) > limit:
            for item in group:
                item.update(status='pending', reason='Competing requests need clarification')
            for item in outcomes:
                if 'duplicate_of' in item and outcomes[item['duplicate_of']]['status'] == 'pending':
                    item.update(status='pending', reason='Competing requests need clarification')
    return outcomes



def requests_need_r5_split(outcomes):
    return any(row['status'] == 'evaluable' and row['requirement_id'] == R5_ELECTIVE
               and row['duration'] == 3 and row['fresh_duration'] for row in outcomes)


def placement_fulfils_request(placement, request):
    """A dated request needs the exact start and training months in its period."""
    option = placement['option']
    months = placement['months']
    if not months or (option['requirement_id'], option['institution'], option['label']) not in request['option_keys']:
        return False
    if months[0] not in request['starts']:
        return False
    if request.get('exact_period'):
        return len(months) == request['duration'] and not placement.get('remaining') and months == request['period_months']
    duration = placement.get('block_duration')
    return duration is None or request.get('duration', duration) == duration


def add_request_objective(model, outcomes, placements, value=lambda variable: variable):
    groups = []
    for i, rows in enumerate(outcomes):
        evaluable = [row for row in rows if row['status'] == 'evaluable' and 'duplicate_of' not in row]
        if not evaluable:
            continue
        flags = []
        for n, row in enumerate(evaluable):
            candidates = [value(p['variable']) for p in placements[i] if placement_fulfils_request(p, row)]
            if model is None:
                flag = max(candidates, default=0)
            else:
                flag = model.new_bool_var(f'request_{i}_{n}')
                model.add_max_equality(flag, candidates or [0])
            flags.append(flag)
        groups.append(flags)
    scale = lcm(*(len(g) for g in groups)) if groups else 1
    return sum((scale // len(g)) * (len(g) - sum(g)) for g in groups)


def unmet_request_reason(person, request, placements, options, stages):
    """Explain proven individual restrictions; do not infer global conflicts."""
    key = request['requirement_id']
    requirement = next(r for r in person['requirements'] if r['requirement_id'] == key)
    if not requirement['remaining_months'] and not any(placement_fulfils_request(p, request) for p in placements):
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
    # Use the scheduler's actual placement choices, including history and LOA.
    possible = [p for p in placements if placement_fulfils_request(p, request)]
    if not possible:
        if all(not person['availability'][m]['available'] for m in request['starts']):
            return 'loa_start', 'Recorded LOA prevents the posting from starting on any permitted date in the requested period.'
        matching = [p for p in placements if (p['option']['requirement_id'], p['option']['institution'], p['option']['label']) in request['option_keys']]
        starts = [p['months'][0] for p in matching if p['months']]
        if matching and (not starts or min(starts) > max(request['starts'])):
            return 'training_progression', 'Outstanding training and required block order prevent a start within the requested period.'
        return 'no_valid_placement', "No placement matches this request under the resident's remaining training and timing rules."
    stage = next((s for s in stages if s['priority'] == 'resident_requests'), None)
    if stage is None:
        unfinished = next((s['priority'] for s in stages
                           if s['priority'] != 'initial_feasibility' and s['status'] != 'optimal'), None)
        activity = {
            'capacity_overflow': 'reducing capacity overflow',
            'incoming_route_distribution': 'balancing incoming R1 routes',
            'monthly_medicine_neurology_ratio': 'balancing Medicine and Neurology by month',
        }.get(unfinished)
        when = f' while {activity},' if activity else ''
        return 'request_search_incomplete', (
            f'The search ended{when} before resident requests were prioritised. More search time may help.')
    if stage['status'] != 'optimal':
        return 'request_search_incomplete', (
            'The search ended before finding the best overall request allocation. More search time may help.')
    return 'not_selected', 'This request was not met in the selected timetable.'
