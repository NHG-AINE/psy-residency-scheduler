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

## Soft constraints

- **Try to fulfil resident requests.** Requests are preferences, not mandatory
  assignments. They must not override hard constraints.
