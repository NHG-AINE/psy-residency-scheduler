# PSY Scheduling Constraints

See [programme-structure.md](programme-structure.md) for the programme overview.

- **Hard constraints** are compulsory rules that every valid
  timetable must satisfy.
- **Soft constraints** are preferences the scheduler tries to
  fulfil using penalties or bonuses, while respecting hard constraints.

## Hard constraints

- **Do not assign postings during LOA.** A resident on LOA for a month must
  not receive a posting in that month.
- **Complete the required postings before progressing.** Unfinished posting
  requirements carry forward, even across academic years. July does not
  automatically advance a resident's R-year.
- **Complete each posting block at the same institution.** Schedule each
  block continuously at one posting and institution for its required duration;
  LOA pauses the block. If a block is partially completed in recognised history, schedule
  its remaining months at the same posting and institution. Flag conflicting
  or unclear partial history for review rather than choosing automatically.
  Preserve recognised Continuity Clinic credit when later historical postings
  or gaps interrupt it; schedule the remainder at the same clinic and institution.
  Multiple disconnected clinic runs still require review rather than being added together.
  Separate completed blocks, including remediation, may be at different
  institutions. Apply each posting's specific duration and timing rules,
  including any permitted division into separate blocks.
- **Use posting history to determine what remains.** The R-year label alone
  does not show which requirements have been fulfilled. Count relevant postings
  across yearly tabs, including a posting that continues across June and July.
- **Respect posting capacity limits.** Enforce the Max value specified for each
  posting in the Postings tab. A blank Max means no capacity limit is imposed
  by that field; it does not mean zero places.
- **Respect mandatory posting remarks.** The schedule must satisfy compulsory
  requirements stated in the Remarks column of the Postings tab.
- **Keep R1 Medicine and Neurology postings within their paired institutions.**
  Pair TTSH General Medicine with NNI Neurology, and SGH General Medicine with
  SGH Neurology. Do not mix these pairings for a resident. The six-month NUH
  Medicine & Neurology posting is a separate combined route.
- **Visit all three clusters during R1-R4.** Each resident must have at least
  one posting in NHG, SHS and NUHS by the end of R4. Count recognised posting
  history towards this cumulative requirement. See [cross-cluster.md](cross-cluster.md)
  for the institution mapping and examples.
- **Do R4 Inpatient Psychiatry outside IMH after completing it at IMH in R1.**
  If a resident completed R1 Inpatient Psychiatry at IMH, their R4 Inpatient
  Psychiatry must be at TTSH, CGH, SGH or NUH. Determine the R1 posting from
  recognised historical evidence.

## Soft constraints

- **Try to fulfil resident requests.** Requests are preferences, not mandatory
  assignments. They must not override hard constraints.
- **Aim for the usual R1 intake distribution.** For an intake of 24 residents,
  target 12 in the TTSH/NNI route, 9 in the SGH route and 3 in the NUH combined
  route. For an intake of 23, retain 12 in TTSH/NNI and 9 in SGH, reducing NUH
  to 2. Adjust for LOA; do not proportionally reduce all three routes for a
  one-resident intake shortfall.
- **Aim for a monthly 2:1 Medicine-to-Neurology split within each R1 pairing.**
  During the first six months of R1, target 8 residents in TTSH General Medicine
  and 4 in NNI Neurology, and 6 in SGH General Medicine and 3 in SGH Neurology
  for the usual intake. Adjust the split for LOA or a smaller cohort; it is not
  an exact mandatory ratio. The NUH combined route is excluded from this split.
- **Increase cluster-exposure priority as R4 completion approaches.** Treat
  new exposure as a low-priority preference in R1-R2. In R3, prioritise missing
  clusters after institution distribution targets. Secure exposure earlier if
  no suitable later posting remains; completion by the end of R4 is mandatory.
  Repeat clusters remain allowed while completion is still feasible. See
  [cross-cluster.md](cross-cluster.md) for the urgency and review rules.
- **Aim to post at least two residents together in the same month.** Prefer
  groups of two or more in the same posting at the same institution; groups
  need not have an even number. A lone resident
  is allowed when the preference cannot be met, including an odd-number
  allocation, but the system should highlight that singleton assignment.
  Peer grouping is the lowest-priority preference across all R-years.
- **Balance residents across posting requirements over time.** Each month,
  aim to spread residents as evenly as practical across the posting requirements
  they are eligible for and still need. Adjust for different posting durations,
  LOA, capacity and remaining requirements. This is a preference, not a fixed
  quota; residents must still complete their required postings. Balance posting
  types separately from the distribution of residents across institutions.
  Balance R2 and R4 posting requirements separately each month. Posting
  balance takes priority over institution allocation, which takes priority over
  peer grouping, across all R-years.
- **Spread placements across institutions using allocation targets.**
  When a posting is offered at IMH and other eligible institutions, give IMH
  two allocation shares and each other institution one share. For N residents
  needing that posting and K eligible institutions including IMH, target
  `floor(N / (K + 1))` residents at each non-IMH institution and assign the
  remainder, `N - (K - 1) * floor(N / (K + 1))`, to IMH.
  For five institutions, 24 residents gives IMH 8 and four at each other site;
  22 residents gives IMH 10 and three at each other site.
  These are soft draft targets, not mandatory quotas or a fixed percentage.
  Allow deviations for capacity limits, cross-cluster requirements, LOA
  and resident requests. Small cohorts need not populate every institution. Apply the formula to the residents needing the posting, not
  automatically to the full intake, and choose assignments together rather
  than filling IMH first. For R4 Consultation Liaison, which has no IMH option,
  aim for an even distribution across eligible institutions.

## Draft preference priority

Apply the following soft preferences in order, while satisfying all hard
constraints. A lower-priority improvement must not worsen a higher-priority
score; compare scores in order rather than adding them into a total.

1. Usual R1 route distribution.
2. Monthly 2:1 Medicine-to-Neurology ratio within each paired route.
3. Balance posting requirements over time.
4. Institution allocation targets: weighted IMH where offered, even R4
   Consultation Liaison allocation otherwise.
5. Missing cluster exposure for residents whose draft reaches R3.
6. Preferred route-to-inpatient destination, as described in
   [cross-cluster.md](cross-cluster.md).
7. Additional R1-R2 cluster exposure.
8. Avoid singleton months for the same posting and institution.

This order applies across the R1-R4 draft. It does not set the priority of
resident requests or replace the hard R4 completion requirement.
