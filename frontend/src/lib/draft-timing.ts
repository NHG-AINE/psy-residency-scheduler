import type { DraftSchedule } from './draft-schedule.ts'

export function draftPhase(priority = 'initial_feasibility', hasRequests = false) {
  switch (priority) {
    case 'initial_feasibility':
      return { id: 'finding', active: 'Finding a valid draft', done: 'Valid draft found' }
    case 'capacity_overflow':
    case 'incoming_route_distribution':
    case 'monthly_medicine_neurology_ratio':
    case 'resident_requests':
      return {
        id: 'balancing',
        active: hasRequests ? 'Balancing capacity and meeting requests' : 'Balancing capacity',
        done: hasRequests ? 'Capacity and requests optimised' : 'Capacity optimised',
      }
    default:
      return { id: 'refining', active: 'Refining placements', done: 'Placements refined' }
  }
}

export function draftTiming(draft: DraftSchedule) {
  const stages = draft.optimisation_stages || []
  const priorities = draft.soft_priority || stages.map((stage) => stage.priority)
  const hasRequests = priorities.includes('resident_requests')
  const phases = new Map<string, { label: string; seconds: number; complete: boolean }>()
  for (const stage of stages) {
    const phase = draftPhase(stage.priority, hasRequests)
    if (!phases.has(phase.id)) {
      const complete = phase.id === 'finding' ? ['feasible', 'optimal'].includes(stage.status)
        : priorities.filter((priority) => draftPhase(priority).id === phase.id)
          .every((priority) => stages.some((item) => item.priority === priority && item.status === 'optimal'))
      phases.set(phase.id, { label: complete ? phase.done : phase.active, seconds: 0, complete })
    }
    phases.get(phase.id)!.seconds += stage.wall_time_seconds
  }
  return [...phases].map(([id, phase]) => ({ id, ...phase }))
}
