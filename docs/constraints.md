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
- **Keep each continuous block at the same posting and institution.** LOA
  pauses the block. When recognised history shows a partially completed block,
  schedule the remaining months at the original posting and institution. Flag
  unclear or conflicting history for review.

  For R3 Continuity Clinic, a later posting or gap does not erase credit already
  earned. Resume the remaining months at the same clinic and institution. If the
  history shows multiple disconnected clinic runs, flag them for review before
  adding their months together.

  Separate completed blocks, including remediation, may take place at different
  institutions. Follow the duration, timing and permitted splits for each posting.

- **Complete 12 months of R5 training.** The default route is 3 months of Child
  & Adolescent Psychiatry, 3 months of Geriatric Psychiatry and 6 months of
  electives. A resident may request 6 months in either core. Extending one core
  leaves 3 elective months. Completing 6 months in each core fills all 12 months.
  Recognised extended core history counts towards these totals.

  For manual edits, require at least 3 months of Child credit and 3 months of
  Geriatric credit across the 12 months. An all-core plan can split Child and
  Geriatric 9+3, 6+6 or 3+9. A 12+0 split in either direction leaves one core
  requirement unmet. Start a 9+3 or 3+9 split through a manual edit. Continue
  that split when recognised postings establish it. For example, six months of
  CGH Geriatric followed by one month of IMH Geriatric leaves two more months
  at IMH and three months of Child. Six months at CGH alone still allows three
  months of Child and three elective months.

- **Count R5 core and elective credit.** The six-month Child and Geriatric
  Psychiatry core posting gives 3 months of Child credit and 3 months of
  Geriatric credit. On the standard combined route, the remaining 6 months
  are electives.

  For an R5 elective that also earns core credit, use the requirement and credit
  specified in the Postings tab. For example, 6 months of IMH Child and EPIP
  give 3 months of Child credit and 3 months of elective credit.

  For both kinds of six-month posting, record a partial block as progress.
  Award the component credits when the resident completes all 6 training months
  at the same posting and institution. LOA pauses the block.

- **Schedule R5 electives in valid blocks.** When a resident has 6 elective
  months to complete, schedule one continuous six-month block by default. If
  an eligible request allows a three-month placement, the scheduler may use two
  continuous three-month blocks. A blank request period qualifies when the
  posting allows a three-month block.

  One qualifying request is enough. The other block may use any eligible
  three-month elective, at the same or a different institution. Follow each
  posting's allowed block lengths and mandatory duration notes. A new allocation
  cannot use a four-month plus two-month split.

  After one recognised three-month block is complete, the resident may choose
  a different eligible posting for the next block. An unfinished block resumes
  at its original posting and institution, even if the original request is
  unavailable.

- **Use posting history to determine what remains.** The R-year label alone
  does not show which requirements have been fulfilled. Count relevant postings
  across yearly tabs, including a posting that continues across June and July.
- **Follow the mandatory timing and duration rules the scheduler recognises in
  the Postings tab.** An unsupported remark does not become a scheduling rule
  automatically.

- **Keep R1 Medicine and Neurology postings within their paired institutions.**
  Pair TTSH General Medicine with NNI Neurology, and SGH General Medicine with
  SGH Neurology. Do not mix these pairings for a resident. The four months of
  General Medicine may be split into two months before and two months after
  the two-month Neurology block, returning to the same Medicine institution.
  The six-month NUH Medicine & Neurology posting is a separate combined route.
- **Visit all three clusters during R1-R4.** Each resident must have at least
  one posting in NHG, SHS and NUHS by the end of R4. Count recognised posting
  history towards this cumulative requirement. Once recognised history shows
  R1-R4 postings are complete, report gaps as historical warnings and proceed
  with remaining R5 planning. See [cross-cluster.md](cross-cluster.md) for the
  institution mapping and examples.
- **Do R4 Inpatient Psychiatry outside IMH after completing it at IMH in R1.**
  Schedule R4 Inpatient Psychiatry at another eligible institution in the
  Postings tab. Count recognised R1 history and any R1 inpatient months
  included in the planned route when checking this rule.

## Soft constraints

- **Minimise months over capacity first.** For each posting and institution,
  compare the number assigned each month with its `Max` in the Postings tab.
  Seven assigned against a max of six adds one to the penalty for that month.
  Add the excess across all posting-months. A blank max has no limit. A max
  of zero counts every assignment as excess.

  Include known occupied places for skipped or excluded residents and original
  timetable cells retained outside generated training. Flag unresolved evidence
  for review. The draft may exceed max. Show staff the affected posting, month
  and assigned residents.

- **Give each resident equal weight when scoring requests.** Score the fraction
  of their eligible request groups fulfilled. Either option fulfils a group of
  two alternatives. Duplicate requests count once, and requests pending
  clarification stay out of the score. All assignments must still meet the hard
  constraints.

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
- **Prefer posting peers together.** Where possible, place at least two
  residents in the same posting at the same institution in the same month.
  A group of three meets the preference. Highlight a resident posted alone
  for review. Peer grouping ranks last.

- **Balance posting types within R2, R4 and R5 separately each month.** Aim for
  an even spread in R2 and R4. In R5, weight the spread by the remaining
  training months for each requirement. LOA, eligibility, capacity and
  higher-priority requests can affect the result.

- **Spread placements across institutions.** For each posting, count the
  residents who need it. If IMH is eligible, give it two shares and each other
  eligible institution one. Round each other institution's target down to a
  whole resident and give the remainder to IMH. With five institutions,
  24 residents gives an 8/4/4/4/4 target and 22 gives 10/3/3/3/3.

  For `N` residents and `K` eligible institutions including IMH, each non-IMH
  target is `floor(N / (K + 1))`. The IMH target is
  `N - (K - 1) * floor(N / (K + 1))`.

  If IMH is outside the eligible set, aim for an even spread. These targets
  may give way to hard constraints and higher-priority preferences. A small
  cohort can leave some institutions empty.

## Draft preference priority

Every draft must satisfy the hard constraints. The scheduler then works through
the preferences below in order. Once it proves the best score for a preference,
it keeps that score while working on the next one. If time runs out, it returns
the best valid draft found so far, provided it has found one.

1. Monthly posting capacity overflow.
2. Usual R1 route distribution.
3. Monthly 2:1 Medicine-to-Neurology ratio within each paired route.
4. Maximise the sum of residents' fulfilled request fractions, giving each resident equal weight.
5. Balance posting requirements over time.
6. Institution allocation targets: weighted IMH where offered, even distribution
   across eligible institutions otherwise.
7. Missing cluster exposure for residents whose draft reaches R3.
8. Preferred route-to-inpatient destination, as described in
   [cross-cluster.md](cross-cluster.md).
9. Additional R1-R2 cluster exposure.
10. Avoid singleton months for the same posting and institution.

This order applies across the R1-R5 draft. It does not replace the hard R4 completion requirement.
