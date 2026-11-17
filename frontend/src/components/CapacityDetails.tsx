import type { CapacityOverflow } from '../lib/draft-schedule'
import { monthLabel } from '../lib/workbook'
import DetailsPopover from './DetailsPopover'

export default function CapacityDetails({ rows, children, openRequest }: { rows: CapacityOverflow[]; children: React.ReactNode; openRequest?: number }) {
  return <DetailsPopover openRequest={openRequest} name="Capacity review" hint={'Over max. ' + rows.map((row) => `${row.residency_year} ${row.label}, ${monthLabel(row.month)}: ${row.assigned} assigned / ${row.max} max`).join('; ') + '. Review all assigned residents'} className="capacity-warning" details={rows.map((row) => <article key={`${row.requirement_id}-${row.institution}-${row.month}`}>
    <p className="request-status pending">{row.residency_year} - {row.label} - {monthLabel(row.month)}</p>
    <p>{row.assigned} assigned / {row.max} max - {row.assigned - row.max} over</p>
    <p className="muted">All assigned residents, across recorded R-years.</p>
    <ul>{row.residents.map((resident, index) => <li key={index}>{resident.name || resident.mcr || 'Unnamed resident'}</li>)}</ul>
  </article>)}>{children}</DetailsPopover>
}
