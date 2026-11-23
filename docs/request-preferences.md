# Resident request preferences

## Which requests does the scheduler use?

For R2–R5 postings, the scheduler reads the posting request and period from the
Requests tab and checks them against the uploaded Postings catalogue and planning
year. Remarks stay in the workbook record and do not affect the schedule.

## How does a request match a posting?

Use the catalogue service name. Include the institution if the resident wants a
particular site. Without an institution, any eligible site offering the matched
service can fulfil the request.

Matching ignores capitalisation and extra spaces, treats `&` and `and` alike, and
ignores `(North)`, `(South)`, `(East)` and `(West)`. Other parentheses can be part
of the service name, as in `Adult Neurodevelopmental Disorders Service (ANDS)`.

A `(Core)` or `(Elective)` suffix restricts the match to that category. Without
a suffix, the scheduler prefers a matching core requirement the resident still
needs. If the core is complete, a uniquely matching unfinished elective can
fulfil the request instead. If the wording still points to several services or
none at all, the request stays pending and the draft can proceed.

## What does the period mean?

| Period in the Requests tab | How the scheduler reads it |
| --- | --- |
| Blank | Start the requested posting at any valid point in the planning year. For example, starting a 12-month Continuity Clinic in January fulfils a blank-period request. The remaining training can continue next year. |
| Jan–Mar 2028 | Start in January and cover January, February and March. A six-month posting starting in January does not fulfil this three-month request. |
| Jan–Jun 2028 | Start in January and cover all six months through June. Either a January–March or an April–June posting alone falls short. |

LOA still pauses training. For a dated request, every requested month must be
covered by the matching placement. If the period is unclear or falls outside the
planning year, flag it for clarification. If the dates are clear but the posting
cannot take that duration, show “Request not met” with the duration reason.

## When can R5 electives split into two blocks?

When a resident has six elective months to schedule, the default is one six-month
block. A request that allows a three-month elective can open a route with two
three-month blocks. One qualifying request is enough. The other block can be any
eligible three-month elective.

For example, a blank-period request for an elective offering both three and six
months allows either duration. A January–June request specifically asks for six
months. If the catalogue requires six months for that elective, a January–March
request cannot shorten it.

For a recognised posting already in progress, a dated request can cover just
the months needed to finish it.

## How are multiple requests scored?

Duplicate rows count once. Distinct requests that fit within the same
requirement can each earn credit. For example, a resident with six elective
months available can have two compatible three-month elective requests fulfilled.

If a resident has only three elective months available and requests two
different three-month electives, treat the requests as alternatives. Either
one fulfils the group, even when the two requests specify different periods.

Each resident has equal weight. A resident with one eligible request group earns
their full share when it is fulfilled. A resident with two eligible groups earns
half their share for each. Pending requests are left out of the score. Hard
constraints and the higher-priority capacity and R1 targets still apply.

## What do the outcomes mean?

| Outcome | Meaning |
| --- | --- |
| Request met | The draft includes a placement that fulfils the request or one of its alternatives. Training credit is assessed separately. |
| Request not met | The scheduler understood the request, but the draft does not fulfil it. Open the details to see what was assigned and the reason available. |
| Pending clarification | The scheduler could not interpret the posting or period well enough to score it. The resident can still receive a draft schedule. |
