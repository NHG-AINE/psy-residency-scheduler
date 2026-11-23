import { draftInsertion, draftSwapLayout, draftSwapOutcome } from './draft-schedule.ts'
import type { DraftChange, DraftChangeResult, DraftSchedule } from './draft-schedule.ts'
import { sameSource } from './workbook.ts'
import type { Source } from './workbook.ts'
import type { SavedDraft } from './workbook-session.ts'

type Month = DraftSchedule['residents'][number]['months'][number]
type Swap = Extract<DraftChange, { kind: 'swap' }>
type Edit = Extract<DraftChange, { kind: 'edit' }>

function residentMonths(draft: DraftSchedule, resident: Source) {
  const months = draft.residents.find((person) => person?.source && sameSource(person.source, resident))?.months
  return Array.isArray(months) ? months : []
}

function touchedMonths(draft: DraftSchedule, change: DraftChange) {
  const months = residentMonths(draft, change.resident)
  const starts = change.kind === 'edit' ? [change.start] : [change.start, change.destination]
  const selected = months.filter((month) => month?.block_start && starts.includes(month.block_start))
  if (change.kind !== 'insert' || selected.length === 0) return selected
  // An insertion can move every intervening block, even between adjacent postings with the same label.
  return months.filter((month) => month?.month >= selected[0].month && month.month <= selected.at(-1)!.month)
}

function assignment(month: Month | undefined) {
  if (!month) return null
  const target = month.target
  const source = target?.source
  return JSON.stringify([month.month, month.status, month.block_start, month.label, target?.requirement_id,
    target?.institution, target?.category, target?.residency_year, source?.sheet, source?.row, source?.column, source?.kind, source?.slot_id])
}

function blockAssignment(month: Month) {
  return assignment({ ...month, month: '', block_start: undefined })
}

function blockStarts(months: Month[]) {
  return months.map((month) => month?.status === 'posting' ? month.block_start : undefined)
}

function reverseLayout(current: Month[], restored: Month[], change: DraftChange | null) {
  if (current.length !== restored.length || current.some((month, index) =>
    month?.month !== restored[index]?.month || month?.status !== restored[index]?.status)) return null
  const currentStarts = blockStarts(current)
  const restoredStarts = blockStarts(restored)
  const forward = change?.kind === 'swap' ? draftSwapLayout(restored, change.start, change.destination)
    : change?.kind === 'insert' ? draftInsertion(restored, change.start, change.destination, change.side)?.blocks : null
  const from = new Map<string, string>()
  const used = new Set<string>()
  const currentBlocks = [...new Set(currentStarts)].filter((start): start is string => !!start)
  const restoredBlocks = [...new Set(restoredStarts)].filter((start): start is string => !!start)
  if (currentBlocks.length !== restoredBlocks.length || change?.kind === 'edit') return null
  if (forward) {
    for (const [index, start] of forward.entries()) {
      const currentStart = currentStarts[index]
      if (!start && !currentStart) continue
      if (!start || !currentStart || (from.has(start) && from.get(start) !== currentStart)
        || (!from.has(start) && used.has(currentStart))) return null
      from.set(start, currentStart); used.add(currentStart)
    }
  } else {
    // Legacy snapshots carry no identity for identical blocks. Prefer a card already at its restored position.
    const signature = (months: Month[], start: string) => JSON.stringify(
      months.filter((month) => month?.block_start === start).map(blockAssignment))
    const signatures = new Map(currentBlocks.map((start) => [start, signature(current, start)]))
    const matches = new Map(restoredBlocks.map((start) => [start, signature(restored, start)]))
    for (const [start, target] of matches) {
      if (signatures.get(start) === target) { from.set(start, start); used.add(start) }
    }
    for (const [start, target] of matches) {
      if (from.has(start)) continue
      const candidate = currentBlocks.find((key) => !used.has(key) && signatures.get(key) === target)
      if (!candidate) return null
      from.set(start, candidate); used.add(candidate)
    }
  }
  const positions = restoredStarts.map((start) => start ? from.get(start) : undefined)
  if (positions.some((start, index) => {
    if (!start) return !!restoredStarts[index] || !!currentStarts[index]
    const at = currentStarts.indexOf(start)
    return at < 0 || blockAssignment(current[at]) !== blockAssignment(restored[index])
  })) return null
  return positions.some((start, index) => start !== currentStarts[index]) ? positions : null
}

export function draftUndoPreview(saved: SavedDraft, restored: DraftSchedule) {
  const change = saved.undoChanges?.at(-1) ?? null
  for (const person of saved.data.residents) {
    if (!person?.source || !Array.isArray(person.months) || (change && !sameSource(person.source, change.resident))) continue
    const current = person.months
    const previous = residentMonths(restored, person.source)
    const positions = reverseLayout(current, previous, change)
    const months = current.flatMap((month, index) => month?.block_start &&
      ((positions && positions[index] !== month.block_start) || assignment(month) !== assignment(previous[index])) ? [month.month] : [])
    if (months.length) return { resident: person.source, name: person.name, positions, months, restored: previous }
  }
  return null
}

function matchesAssignments(actual: DraftSchedule, expected: DraftSchedule, reversal?: { resident: Source; months: Map<string, Month> }) {
  return actual.residents.length === expected.residents.length && expected.residents.every((person, index) => {
    const other = actual.residents[index]
    if (!person?.source || !other?.source || !sameSource(other.source, person.source)
      || !Array.isArray(person.months) || !Array.isArray(other.months) || person.months.length !== other.months.length) return false
    const restored = reversal && sameSource(person.source, reversal.resident) ? reversal.months : undefined
    return person.months.every((month, monthIndex) => assignment(restored?.get(month?.month) ?? month) === assignment(other.months[monthIndex]))
  })
}

function matchesPlan(actual: DraftSchedule, expected: DraftSchedule) {
  return matchesAssignments(actual, expected) && actual.residents.every(({ route, carryforward }, index) => {
    const original = expected.residents[index]
    const remaining = (rows: typeof carryforward) => rows?.map(({ requirement_id, institution, months, label }) =>
      JSON.stringify([requirement_id, institution, months, label])).sort().join('\n')
    return route === original.route && remaining(carryforward) === remaining(original.carryforward)
  })
}

export function draftBaseline(saved: SavedDraft | null): DraftSchedule | null {
  return saved?.undo?.[0] ?? saved?.data ?? null
}

export function restoreGeneratedDraft(saved: SavedDraft): SavedDraft {
  const original = draftBaseline(saved)
  if (!saved.undo?.length || !original || !['feasible', 'optimal'].includes(original.status) || !matchesPlan(saved.data, original)) return saved
  return { ...saved, data: original, undo: [], undoChanges: [] }
}

function asSwap(draft: DraftSchedule, change: DraftChange): Swap | null {
  if (change.kind !== 'insert') return change.kind === 'swap' ? change : null
  const span = touchedMonths(draft, change).filter((month) => month.status === 'posting')
  const first = span.filter((month) => month.block_start === change.start)
  const second = span.filter((month) => month.block_start === change.destination)
  if (!first.length || first.length !== second.length || first.length + second.length !== span.length) return null
  return { kind: 'swap', resident: change.resident, start: change.start, destination: change.destination }
}

function inferChange(before: DraftSchedule, after: DraftSchedule): Swap | Edit | null {
  for (const person of before.residents) {
    if (!person?.source || !Array.isArray(person.months)) continue
    const updated = residentMonths(after, person.source)
    const starts = new Set(person.months.filter((month, i) => assignment(month) !== assignment(updated[i])).map((month) => month?.block_start))
    if (!starts.size) continue
    const [start, destination] = starts
    if (starts.size === 1 && start) {
      const incoming = updated.find((month) => month?.block_start === start)
      const target = incoming?.target?.source
      const option = target && after.edit_options?.find(({ source }) => sameSource(source, target) && source.column === target.column)
      if (!option || !incoming) return null
      const months = new Map(person.months.filter((month) => month?.block_start === start).map((month) =>
        [month.month, { ...month, label: incoming.label, target: incoming.target }] as const))
      return matchesAssignments(after, before, { resident: person.source, months })
        ? { kind: 'edit', resident: person.source, start, posting: option.posting, institution: option.institution, offering: option.source }
        : null
    }
    if (starts.size !== 2 || !start || !destination) return null
    const first = person.months.filter((month) => month?.block_start === start)
    const second = person.months.filter((month) => month?.block_start === destination)
    if (!first.length || first.length !== second.length) return null
    const months = new Map<string, Month>()
    for (const [block, incoming] of [[first, second[0]], [second, first[0]]] as const) {
      for (const month of block) months.set(month.month, { ...month, label: incoming.label, target: incoming.target })
    }
    if (!matchesAssignments(after, before, { resident: person.source, months })) return null
    return { kind: 'swap', resident: person.source, start, destination }
  }
  return null
}

function reversalMonths(before: DraftSchedule, previous: DraftChange, change: Edit | Swap, dates: Set<string>) {
  const prior = previous.kind === 'edit' ? previous : asSwap(before, previous)
  if (!dates.size || !prior || prior.kind !== change.kind || !sameSource(prior.resident, change.resident)) return null
  if (prior.kind === 'edit' && prior.start !== change.start) return null
  if (prior.kind === 'swap' && change.kind === 'swap') {
    const starts = [change.start, change.destination]
    if (!starts.includes(prior.start) || !starts.includes(prior.destination)) return null
  }
  const touched = touchedMonths(before, prior)
  if (touched.length !== dates.size || touched.some((month) => !dates.has(month.month))) return null
  return { resident: change.resident, months: new Map(touched.map((month) => [month.month, month])) }
}

export function restoreDraftEditHistory(saved: SavedDraft): SavedDraft {
  const original = restoreGeneratedDraft(saved)
  if (original !== saved || !saved.undo?.length) return original

  const snapshots = [...saved.undo, saved.data]
  const undo: DraftSchedule[] = []
  const undoChanges: (DraftChange | null)[] = []
  let data = snapshots[0]
  for (const [index, snapshot] of snapshots.slice(1).entries()) {
    const change = saved.undoChanges?.[index] ?? inferChange(snapshots[index], snapshot)
    const before = undo.at(-1)
    const previous = undoChanges.at(-1)
    if (change?.kind === 'edit' && before && previous?.kind === 'edit'
      && reversalMonths(before, previous, change, new Set(touchedMonths(data, change).map(({ month }) => month)))
      && matchesPlan(snapshot, before)) {
      undo.pop()
      undoChanges.pop()
      data = before
    } else {
      undo.push(data)
      undoChanges.push(change)
      data = snapshot
    }
  }
  return undo.length === saved.undo.length ? saved : { ...saved, data, undo, undoChanges }
}

export async function prepareDraftEdit(saved: SavedDraft, change: DraftChange, validated: DraftSchedule,
  replay: (draft: DraftSchedule, change: DraftChange) => Promise<DraftChangeResult>): Promise<SavedDraft> {
  const undo = saved.undo ?? []
  const recorded = saved.undoChanges ?? undo.map(() => null)
  const chronological = { ...saved, data: validated, undo: [...undo, saved.data], undoChanges: [...recorded, change] }
  const original = restoreGeneratedDraft(chronological)
  if (original !== chronological) return original
  const reversible = change.kind === 'edit' ? change : asSwap(saved.data, change)
  if (!reversible) return chronological

  const changes = recorded.map((step, index) => step ?? inferChange(undo[index], undo[index + 1] ?? saved.data))
  const current = touchedMonths(saved.data, reversible)
  const dates = new Set(current.map((month) => month.month))
  for (let index = undo.length - 1; index >= 0; index--) {
    const previous = changes[index]
    if (!previous) break
    if (!sameSource(previous.resident, change.resident)) continue

    const before = undo[index]
    if (!touchedMonths(before, previous).some((month) => dates.has(month.month))) continue
    const reversal = reversalMonths(before, previous, reversible, dates)
    if (!reversal) break
    const historicalAfter = undo[index + 1] ?? saved.data
    const prior = residentMonths(historicalAfter, change.resident).filter((month) => dates.has(month?.month))
    if (prior.length !== current.length || prior.some((month, i) => assignment(month) !== assignment(current[i]))) break

    if (!matchesAssignments(validated, saved.data, reversal)) break

    let data = before
    const rebased = undo.slice(0, index)
    try {
      for (let later = index + 1; later < undo.length; later++) {
        const operation = changes[later]
        if (!operation) return chronological
        const result = await replay(data, operation)
        if (draftSwapOutcome(result) === 'blocked' || !result.draft
          || !matchesAssignments(result.draft, undo[later + 1] ?? saved.data, reversal)) return chronological
        rebased.push(data)
        data = result.draft
      }
    } catch {
      return chronological
    }
    if (!matchesPlan(data, validated)) return chronological
    return { ...saved, data, undo: rebased, undoChanges: changes.filter((_, i) => i !== index) }
  }
  return chronological
}

export function undoDraftEdit(saved: SavedDraft | null): SavedDraft | null {
  const previous = saved?.undo?.at(-1)
  return saved && previous ? { ...saved, data: previous, undo: saved.undo?.slice(0, -1), undoChanges: saved.undoChanges?.slice(0, -1) } : null
}
