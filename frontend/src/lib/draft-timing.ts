import type { DraftSchedule } from './draft-schedule.ts'

const labels: Record<string, string> = {
  incoming_route_distribution: 'R1 route distribution',
  monthly_medicine_neurology_ratio: 'R1 Medicine / Neurology ratio',
  resident_requests: 'Resident requests',
  posting_balance: 'Posting balance',
  inpatient_allocation: 'Institution allocation',
  r3_missing_clusters: 'R3 cluster exposure',
  inpatient_destination: 'Preferred inpatient destination',
  missing_clusters: 'R1-R2 cluster exposure',
  singleton_months: 'Peer grouping',
}

export function draftTiming(draft: DraftSchedule) {
  const stages = draft.optimisation_stages || []
  return (draft.soft_priority || stages.map((stage) => stage.priority)).map((priority) => {
    const stage = stages.find((item) => item.priority === priority)
    const status = stage?.status
    return {
      priority, label: labels[priority] || priority.replaceAll('_', ' '),
      seconds: stage?.wall_time_seconds, status,
      outcome: !stage ? 'Not reached' : status === 'optimal' ? 'Optimal'
        : status === 'feasible' ? 'Best found - not proven'
        : status === 'unknown' ? 'No new solution' : 'Stopped',
    }
  })
}
