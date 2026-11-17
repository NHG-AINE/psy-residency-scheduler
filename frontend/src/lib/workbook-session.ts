import type { Workbook } from './workbook.ts'
import { isWorkbook, workbookError } from './workbook.ts'
import type { DraftSchedule } from './draft-schedule.ts'

export type SavedDraft = { year: number; data: DraftSchedule; elapsedSeconds: number; reviewSignature: string }
export type WorkbookSession = { version: 1; file: File; fileName: string; lastModified: number; workbook: Workbook; draft: SavedDraft | null }

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
    || !['optimal', 'feasible'].includes(saved.draft.data?.status)
    || !Array.isArray(saved.draft.data.residents) || !Array.isArray(saved.draft.data.blockers)
    || saved.draft.data.residents.some((person) => !Array.isArray(person?.months) || !Array.isArray(person?.carryforward)))) {
    throw new Error('The saved draft could not be read. Choose the workbook again.')
  }
  return { ...saved, file: new File([saved.file], saved.fileName, { type: saved.file.type, lastModified: saved.lastModified }), draft: saved.draft || null }
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
