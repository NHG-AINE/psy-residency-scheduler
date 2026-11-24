import type { DraftChangeIssue } from './draft-schedule.ts'

type WarningLine = { severity: DraftChangeIssue['severity']; title?: string; description: string }

// Saved drafts and Undo use the original messages. Format them only for display.
const monthNames = 'January February March April May June July August September October November December'.split(' ')
function period(start: string, end = start) {
  const first = start.slice(0, 3), last = end.slice(0, 3)
  if (start === end) return first
  return (monthNames.indexOf(start) + 1) % 12 === monthNames.indexOf(end)
    ? `${first} and ${last}` : `${first} to ${last}`
}

function warningLine(issue: DraftChangeIssue): WarningLine {
  const { severity, message, code } = issue
  const line = (title: string, description: string) => ({ severity, title, description })
  if (severity === 'soft') {
    let m: RegExpMatchArray | null
    switch (code) {
      case 'capacity_overflow':
        m = message.match(/^(\w+)(?: to (\w+))? at (.+?) would have (\d+ residents?) in (.+)\. The max is (\d+)\.$/)
        if (m) return line('Capacity exceeded', `${m[3]} ${m[5]} has ${m[4]} in ${period(m[1], m[2])} (max ${m[6]}).`)
        break
      case 'resident_requests':
        m = message.match(/^The request for (.+) would no longer be met\.$/s)
        if (m) {
          const names = m[1].split(' or ')
          if (names.length === 2) return line('No requested option met', `Neither ${names[0]} nor ${names[1]}.`)
          return line(names.length > 1 ? 'No requested option met' : 'Request no longer met', m[1] + '.')
        }
        break
      case 'incoming_route_distribution':
        m = message.match(/^The (.+) route would have (\d+ residents?)\. The target for this intake is (\d+)\.$/)
        if (m) return line('Route intake off target', `The ${m[1]} route has ${m[2]} this intake (target ${m[3]}).`)
        break
      case 'posting_balance':
        m = message.match(/^The monthly spread would be less even\. In (\w+), (\d+ residents?) would be assigned to (.+)\.$/)
        if (m) return line('Less even posting spread', `${m[2]} in ${m[3]} in ${period(m[1])}.`)
        break
      case 'inpatient_allocation':
        m = message.match(/^(.+) would have (\d+ residents?) in (.+)\. The target is (\d+)\.$/)
        if (m) return line('Site allocation off target', `${m[1]} ${m[3]} has ${m[2]} (target ${m[4]}).`)
        m = message.match(/^(.+) would have (\d+ residents?) at (.+?) and (\d+) at (.+)\. The programme aims for an even spread\.$/)
        if (m) return line('Uneven site allocation', `${m[1]} has ${m[2]} at ${m[3]} and ${m[4]} at ${m[5]}.`)
        break
      case 'inpatient_destination':
        m = message.match(/^After the (.+) route, (.+) is preferred for inpatient training\. This block is at (.+)\.$/)
        if (m) return line('Preferred cluster missed', `The inpatient block is at ${m[3]}. The ${m[1]} route prefers ${m[2]}.`)
        break
      case 'r3_missing_clusters':
      case 'missing_clusters':
        m = message.match(/^This would remove the resident['’]s planned (.+) exposure\./)
        if (m) return line('Planned cluster exposure lost', `The resident loses ${m[1]} exposure and needs all three clusters by the end of R4.`)
        m = message.match(/^The resident would have fewer opportunities to train in a new cluster during (.+)\.$/)
        if (m) return line('Fewer cluster opportunities', `The resident has fewer chances to train in a new cluster during ${m[1]}.`)
        break
      case 'singleton_months':
        m = message.match(/^(.+) would be the only resident in (.+) (?:in|from) (\w+)(?: to (\w+))?\.$/)
        if (m) return line('Only resident', `${m[1]} is the only resident in ${m[2]} during ${period(m[3], m[4])}.`)
    }
  }
  return { severity, description: message }
}

export function draftWarningLines(issues: DraftChangeIssue[]): WarningLine[] {
  const lines: WarningLine[] = []
  type Run = { start: string; end: string; medicine: string; neurology: string }
  const routes = new Map<string, { line: WarningLine; runs: Run[] }>()
  for (const issue of issues) {
    const ratio = issue.severity === 'soft' && issue.code === 'monthly_medicine_neurology_ratio'
      && issue.message.match(/^In (\w+), the (.+) route would have (\d+) in Medicine and (\d+) in Neurology\. The usual split is 2 to 1\.$/)
    if (!ratio) {
      lines.push(warningLine(issue))
      continue
    }
    const [, month, route, medicine, neurology] = ratio
    let group = routes.get(route)
    if (!group) {
      group = { line: { severity: 'soft', title: 'R1 ratio off target', description: '' }, runs: [] }
      routes.set(route, group)
      lines.push(group.line)
    }
    const last = group.runs.at(-1)
    if (last && last.medicine === medicine && last.neurology === neurology
      && (monthNames.indexOf(last.end) + 1) % 12 === monthNames.indexOf(month)) last.end = month
    else group.runs.push({ start: month, end: month, medicine, neurology })
  }
  for (const [route, { line, runs }] of routes) {
    const counts = runs.map((r, i) => `${r.medicine}${i === 0 ? ' Medicine' : ''} to ${r.neurology}${i === 0 ? ' Neurology' : ''} in ${period(r.start, r.end)}`)
    line.description = `${route} has ${new Intl.ListFormat('en').format(counts)}. The usual split is 2 to 1.`
  }
  return lines
}
