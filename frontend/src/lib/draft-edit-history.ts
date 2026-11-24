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

function affectedMonths(draft: DraftSchedule, change: DraftChange) {
  if (change.kind === 'insert') {
    const months = residentMonths(draft, change.resident)
    const insertion = draftInsertion(months, change.start, change.destination, change.side)
    if (insertion) {
      const starts = new Map<string, string>()
      insertion.blocks.forEach((block, index) => {
        if (block && !starts.has(block)) starts.set(block, months[index].month)
      })
      return months.filter((month, position) => {
        const block = insertion.blocks[position]
        return !!block && (block !== month.block_start || starts.get(block) !== month.block_start)
      })
    }
  }
  return touchedMonths(draft, change)
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

export function draftUndoPreview(saved: SavedDraft, restored: DraftSchedule, change = saved.undoChanges?.at(-1) ?? null) {
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

export function draftBlockUndoTargets(saved: SavedDraft | null) {
  type Entry = { index: number; change: DraftChange | null }
  const residentKey = (source: Source) => JSON.stringify(source.kind ? [source.kind, source.slot_id] : [source.sheet, source.row])
  const calendar = new Map<string, Map<string, Entry>>()
  function record(resident: Source, months: Month[], entry: Entry) {
    const key = residentKey(resident)
    const dates = calendar.get(key) ?? new Map<string, Entry>()
    for (const month of months) dates.set(month.month, entry)
    calendar.set(key, dates)
  }
  for (let index = 0; saved?.undo && index < saved.undo.length; index++) {
    const before = saved.undo[index]
    const after = saved.undo[index + 1] ?? saved.data
    const change = saved.undoChanges?.[index] ?? inferChange(before, after)
    if (change) {
      record(change.resident, affectedMonths(before, change), { index, change })
    } else {
      // A legacy snapshot may show the assignments but leave the operation ambiguous.
      for (const person of before.residents) {
        if (!person?.source || !Array.isArray(person.months)) continue
        const current = residentMonths(after, person.source)
        const changed = person.months.filter((month, position) => month && assignment(month) !== assignment(current[position]))
        if (changed.length) record(person.source, changed, { index, change: null })
      }
    }
  }
  const targets = new Map<string, Map<string, Entry>>()
  for (const person of saved?.data.residents ?? []) {
    if (!person?.source || !Array.isArray(person.months)) continue
    const key = residentKey(person.source)
    const dates = calendar.get(key)
    if (!dates) continue
    const blocks = new Map<string, Entry>()
    for (const month of person.months) {
      if (!month?.block_start) continue
      const entry = dates.get(month.month)
      if (entry && entry.index > (blocks.get(month.block_start)?.index ?? -1)) blocks.set(month.block_start, entry)
    }
    targets.set(key, blocks)
  }
  return (resident: Source, start: string) => {
    const entry = targets.get(residentKey(resident))?.get(start)
    return entry?.change ? { index: entry.index, change: entry.change } : null
  }
}

export function draftBlockUndoTarget(saved: SavedDraft | null, resident: Source, start: string) {
  return draftBlockUndoTargets(saved)(resident, start)
}

function changedBlockStarts(before: DraftSchedule, after: DraftSchedule, change: DraftChange) {
  const restored = residentMonths(before, change.resident)
  const current = residentMonths(after, change.resident)
  const positions = reverseLayout(current, restored, change)
  if (!positions) return null
  const starts = new Map<string, string>()
  positions.forEach((start, index) => {
    const previousStart = restored[index].block_start
    if (start && previousStart && start !== previousStart) starts.set(start, previousStart)
  })
  return starts
}

function acceptedWarnings(issues: DraftChangeResult['issues'], after: DraftSchedule) {
  return issues.every((issue) => issue.severity === 'soft' && after.edit_warnings?.some((accepted) =>
    accepted.severity === issue.severity && accepted.code === issue.code && accepted.message === issue.message
    && issue.affected.every(({ month, source }) =>
      accepted.affected.some((cell) => cell.month === month && sameSource(cell.source, source)))))
}

export async function undoDraftBlock(saved: SavedDraft, resident: Source, start: string,
  replay: (draft: DraftSchedule, change: DraftChange) => Promise<DraftChangeResult>): Promise<SavedDraft | null> {
  const target = draftBlockUndoTarget(saved, resident, start)
  if (!target || !saved.undo) return null
  const { index, change } = target
  if (index === saved.undo.length - 1) return undoDraftEdit(saved)

  const snapshots = [...saved.undo, saved.data]
  const next = saved.undo.slice(0, index)
  const changes = next.map((snapshot, step) => saved.undoChanges?.[step] ?? inferChange(snapshot, snapshots[step + 1]))
  // Later edits follow their block to its restored dates. A later overlapping move
  // can change which blocks its span includes, so leave that move for the user to undo first.
  const relocated = change.kind === 'edit' ? new Map<string, string>() : changedBlockStarts(snapshots[index], snapshots[index + 1], change)
  if (!relocated) throw new Error('Use toolbar Undo first. This move’s original block positions could not be recovered.')
  let data = snapshots[index]
  for (let step = index + 1; step < saved.undo.length; step++) {
    const before = snapshots[step]
    const after = snapshots[step + 1]
    const operation = saved.undoChanges?.[step] ?? inferChange(before, after)
    if (!operation) throw new Error('Use toolbar Undo first. A later change could not be identified in the saved history.')
    const blockMap = sameSource(resident, operation.resident) ? relocated : null
    const touched = touchedMonths(before, operation)
    const actual = residentMonths(data, operation.resident)
    const updated = residentMonths(after, operation.resident)
    const planned = new Map<string, Month>()
    let replayed = operation
    if (operation.kind === 'edit') {
      const restoredStart = blockMap?.get(operation.start) ?? operation.start
      const restoredBlock = actual.filter((month) => month.block_start === restoredStart)
      const edited = updated.find((month) => month.block_start === operation.start)
      if (!edited || !touched.length || restoredBlock.length !== touched.length
        || restoredBlock.some((month, position) => blockAssignment(month) !== blockAssignment(touched[position]))) {
        throw new Error('Undo the later posting edit first. It depends on this change.')
      }
      for (const month of restoredBlock) planned.set(month.month, { ...month, label: edited.label, target: edited.target })
      replayed = { ...operation, start: restoredStart }
    } else {
      const moved = affectedMonths(before, operation)
      const dates = new Set(moved.map(({ month }) => month))
      if (!dates.size || touched.some((month) => month.block_start && blockMap?.has(month.block_start))
        || moved.some((month) => assignment(month) !== assignment(actual.find((entry) => entry.month === month.month)))) {
        throw new Error('Undo the later posting move first. It depends on this change.')
      }
      for (const month of updated) if (dates.has(month.month)) planned.set(month.month, month)
    }

    const result = await replay(data, replayed)
    if (!result.draft || draftSwapOutcome(result) === 'blocked') {
      throw new Error(`This change could not be undone while keeping a later ${operation.kind === 'edit' ? 'posting edit' : 'posting move'}. ${result.issues.map(({ message }) => message).join(' ')}`.trim())
    }
    if (!matchesAssignments(result.draft, data, { resident: operation.resident, months: planned })) {
      throw new Error('Undo the dependent change first. Keeping it would change another posting or block boundary.')
    }
    if (!acceptedWarnings([...result.issues, ...(result.draft.edit_warnings ?? [])], after)) {
      throw new Error('Undo the later change first. Keeping it would introduce a new draft warning.')
    }
    next.push(data)
    changes.push(replayed)
    data = result.draft
  }
  return { ...saved, data, undo: next, undoChanges: changes }
}
