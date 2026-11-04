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
- **Prefer postings in clusters not yet visited.** Use future assignments to
  work towards the R1-R4 cross-cluster requirement. This does not prohibit a
  repeat cluster before R4. See [cross-cluster.md](cross-cluster.md).
- **Aim to post at least two residents together in the same month.** Prefer
  groups of two or more in the same posting at the same institution; groups
  need not have an even number. A lone resident
  is allowed when the preference cannot be met, including an odd-number
  allocation, but the system should highlight that singleton assignment.
- **Prefer a larger allocation to IMH.** When a posting is offered at IMH
  and other institutions, aim to allocate more residents to IMH than to each
  other institution individually, not necessarily more than all others combined.
  No fixed number or percentage is prescribed. Allow exceptions for capacity
  limits, cross-cluster requirements, LOA, resident requests and peer grouping.
