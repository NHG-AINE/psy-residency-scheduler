import type { Workbook } from './workbook.ts'
import { isWorkbook, sameSource, workbookError } from './workbook.ts'
import { restoreDraftEditHistory } from './draft-edit-history.ts'
import type { DraftChange, DraftSchedule } from './draft-schedule.ts'

export type SavedDraft = { year: number; data: DraftSchedule; elapsedSeconds: number; reviewSignature: string;
  undo?: DraftSchedule[]; undoChanges?: (DraftChange | null)[] }
export type WorkbookSession = { version: 1; file: File; fileName: string; lastModified: number; workbook: Workbook; draft: SavedDraft | null }

function restoreSplitMedicine(draft: DraftSchedule, previous: DraftSchedule | undefined): DraftSchedule {
  if (draft.status !== 'edited' || !previous) return draft
  const medicine = 'r1.general_medicine'
  const neurology = 'r1.neurology'
  const residents = draft.residents.map((resident) => {
    if (!resident?.source || !Array.isArray(resident.months)) return resident
    const block = resident.months.filter((month) => month?.status === 'posting' && month.target?.requirement_id === medicine)
    if (block.length !== 4) return resident
    const start = block[0].month
    const split = block[2].month
    if (!block.every((month) => month.block_start === start)) return resident

    const prior = previous.residents.find((person) => person?.source && sameSource(person.source, resident.source))
    if (!Array.isArray(prior?.months)) return resident
    // Restore a boundary only when undo history shows both two-month slots at these dates.
    for (const [index, blockStart] of [start, split].entries()) {
      const old = prior.months.filter((month) => month?.status === 'posting' && month.block_start === blockStart)
      const requirement = old[0]?.target?.requirement_id
      if (old.length !== 2 || (requirement !== medicine && requirement !== neurology)
        || old.some((month, offset) => month.target?.requirement_id !== requirement || month.month !== block[index * 2 + offset].month)) return resident
    }
    const secondHalf = block.slice(2)
    const months = resident.months.map((month) => secondHalf.includes(month) ? { ...month, block_start: split } : month)
    return { ...resident, months }
  })
  return { ...draft, residents }
}

export function parseSession(value: unknown): WorkbookSession | null {
  if (value === undefined || value === null) return null
  const saved = value as WorkbookSession
  if (saved.version !== 1) throw new Error('The saved workbook uses an unsupported version. Choose the workbook again.')
  if (!(saved.file instanceof Blob) || typeof saved.fileName !== 'string' || !Number.isFinite(saved.lastModified)
    || !isWorkbook(saved.workbook) || workbookError([{ name: saved.fileName, size: saved.file.size }])) {
    throw new Error('The saved workbook could not be read. Choose the workbook again.')
  }
  if (saved.draft && (!Number.isInteger(saved.draft.year)
    || saved.draft.year !== Math.max(...saved.workbook.available_years.map((item) => item.year))
    || typeof saved.draft.reviewSignature !== 'string'
    || !Number.isFinite(saved.draft.elapsedSeconds) || saved.draft.elapsedSeconds < 0
    || !['optimal', 'feasible', 'edited'].includes(saved.draft.data?.status)
    || !Array.isArray(saved.draft.data.residents) || !Array.isArray(saved.draft.data.blockers)
    || saved.draft.data.residents.some((person) => !Array.isArray(person?.months) || !Array.isArray(person?.carryforward))
    || (saved.draft.undo !== undefined && (!Array.isArray(saved.draft.undo) || saved.draft.undo.some((data) =>
      !['optimal', 'feasible', 'edited'].includes(data?.status) || !Array.isArray(data.residents) || !Array.isArray(data.blockers)))))) {
    throw new Error('The saved draft could not be read. Choose the workbook again.')
  }
  let draft = saved.draft || null
  if (draft?.undo?.length && draft.undoChanges === undefined) {
    const undo: DraftSchedule[] = []
    for (const snapshot of draft.undo) undo.push(restoreSplitMedicine(snapshot, undo.at(-1)))
    draft = { ...draft, data: restoreSplitMedicine(draft.data, undo.at(-1)), undo }
  }
  if (draft && draft.undoChanges !== undefined) {
    const changes = draft.undoChanges
    if (!Array.isArray(changes) || changes.length !== (draft.undo?.length ?? 0) || changes.some((change) =>
      change !== null && (!change?.resident || typeof change.start !== 'string' || !['edit', 'swap', 'insert'].includes(change.kind)))) {
      draft = { ...draft, undoChanges: (draft.undo ?? []).map(() => null) }
    }
  }
  return { ...saved, file: new File([saved.file], saved.fileName, { type: saved.file.type, lastModified: saved.lastModified }),
    draft: draft ? restoreDraftEditHistory(draft) : null }
}

async function accessSession(value?: WorkbookSession | null): Promise<unknown> {
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    let finished = false
    const timer = setTimeout(() => { finished = true; reject(new Error('Browser workbook storage is unavailable.')) }, 2000)
    const request = indexedDB.open('psy-workbook-session', 1)
    request.onupgradeneeded = () => { if (!request.result.objectStoreNames.contains('session')) request.result.createObjectStore('session') }
    request.onsuccess = () => {
      clearTimeout(timer)
      if (finished) { request.result.close(); return }
      finished = true
      request.result.onversionchange = () => request.result.close()
      resolve(request.result)
    }
    request.onerror = request.onblocked = () => {
      clearTimeout(timer); finished = true; reject(new Error('Browser workbook storage is unavailable.'))
    }
  })
  return new Promise((resolve, reject) => {
    const transaction = database.transaction('session', value === undefined ? 'readonly' : 'readwrite')
    const store = transaction.objectStore('session')
    const request = value === undefined ? store.get('current') : value === null ? store.delete('current') : store.put(value, 'current')
    const timer = setTimeout(() => { try { transaction.abort() } catch { /* Completion may already be queued. */ } }, 2000)
    const close = () => { clearTimeout(timer); database.close() }
    transaction.oncomplete = () => { close(); resolve(request.result) }
    transaction.onabort = transaction.onerror = () => { close(); reject(new Error('The browser could not save or restore the workbook. Storage may be full or disabled.')) }
  })
}

// Serial transactions keep a later Remove/Discard ahead of superseded queued saves.
export function sessionWriter(write: (value: WorkbookSession | null) => Promise<unknown> = accessSession) {
  let revision = 0
  let pending = Promise.resolve()
  return (value: WorkbookSession | null): Promise<void> => {
    const current = ++revision
    pending = pending.catch(() => {}).then(async () => { if (current === revision) await write(value) })
    return pending
  }
}
export const saveSession = sessionWriter()
export async function restoreSession(): Promise<WorkbookSession | null> { return parseSession(await accessSession()) }
