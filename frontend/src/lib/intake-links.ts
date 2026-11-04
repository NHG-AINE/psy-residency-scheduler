import type { Resident, Source, Workbook } from './workbook'

export const INTAKE_STORAGE_KEY = 'psy-intake-links-v1'
export type IntakeLink = { year: number; slot_id: string; mcr: string; name: string
  postings: { month: string; value: string | null; status: 'blank' | 'loa' | 'posting'; source: Source }[] }
export type IntakeLinkStore = { version: 1; links: IntakeLink[] }
export type IntakeLinkState = Pick<IntakeLink, 'year' | 'slot_id' | 'mcr' | 'name'> & { status: 'applied' | 'needs_review' | 'other_year'; message: string }
export const emptyIntakeStore = (): IntakeLinkStore => ({ version: 1, links: [] })
const normalized = (value: string) => value.trim().replace(/\s+/g, ' ').toLowerCase()
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const fields = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).every((key) => keys.includes(key))
const text = (value: unknown): value is string => typeof value === 'string' && !!value.trim() && value.length <= 2000

export function parseIntakeStore(raw: string): IntakeLinkStore {
  let value: unknown
  try { value = JSON.parse(raw) } catch { throw new Error('Intake links are not valid JSON. Choose an exported intake-link file.') }
  if (!object(value) || !fields(value, ['version', 'links']) || value.version !== 1 || !Array.isArray(value.links) || value.links.length > 500) throw new Error('Expected version 1 and at most 500 intake links.')
  const slots = new Set<string>(), people = new Set<string>()
  for (const link of value.links) {
    if (!object(link) || !fields(link, ['year', 'slot_id', 'mcr', 'name', 'postings']) || !Number.isInteger(link.year)
      || Number(link.year) < 1900 || Number(link.year) > 9998 || !text(link.mcr) || !text(link.name)
      || typeof link.slot_id !== 'string' || !Array.isArray(link.postings) || link.postings.length > 12) throw new Error('An intake link has invalid identity, year or postings. Nothing was imported.')
    const number = link.slot_id.replace(`intake-${link.year}-slot-`, '')
    if (!/^[0-9]+$/.test(number) || Number(number) < 1 || link.slot_id !== `intake-${link.year}-slot-${String(Number(number)).padStart(2, '0')}`) throw new Error('An intake slot ID does not match its year.')
    const months = new Set<string>()
    for (const posting of link.postings) {
      if (!object(posting) || !fields(posting, ['month', 'value', 'status', 'source']) || typeof posting.month !== 'string'
        || !/^\d{4}-(0[1-9]|1[0-2])$/.test(posting.month) || posting.month < `${link.year}-07` || posting.month > `${Number(link.year) + 1}-06`
        || months.has(posting.month) || !(posting.value === null || typeof posting.value === 'string' && posting.value.length <= 2000) || !object(posting.source)) throw new Error('Slot months must be unique and within the intake year.')
      const label = normalized(posting.value || ''), ref = posting.source
      const status = !label ? 'blank' : label === 'loa' ? 'loa' : 'posting'
      const physical = fields(ref, ['sheet', 'row', 'column']) && text(ref.sheet) && Number.isInteger(ref.row) && Number(ref.row) > 0 && (ref.column === undefined || typeof ref.column === 'string')
      const generated = fields(ref, ['kind', 'slot_id']) && ref.kind === 'intake_placeholder' && ref.slot_id === link.slot_id
      if (posting.status !== status || !(physical || generated)) throw new Error('A slot posting has an invalid status or source.')
      months.add(posting.month)
    }
    const person = `${link.year}:${normalized(link.mcr)}`
    if (slots.has(link.slot_id) || people.has(person)) throw new Error('Duplicate or conflicting intake links. Nothing was imported.')
    slots.add(link.slot_id); people.add(person)
  }
  return value as unknown as IntakeLinkStore
}

export function mergeIntakeStores(current: IntakeLinkStore, incoming: IntakeLinkStore): IntakeLinkStore {
  const links = [...current.links]
  for (const link of incoming.links) {
    const prior = links.find((saved) => saved.slot_id === link.slot_id)
    if (prior && JSON.stringify(prior) === JSON.stringify(link)) continue
    links.push(link)
  }
  return parseIntakeStore(JSON.stringify({ version: 1, links }))
}

export function readIntakeStore(storage: Pick<Storage, 'getItem'>): IntakeLinkStore {
  const raw = storage.getItem(INTAKE_STORAGE_KEY)
  return raw ? parseIntakeStore(raw) : emptyIntakeStore()
}

export function writeIntakeStore(storage: Pick<Storage, 'getItem' | 'setItem'>, store: IntakeLinkStore, expected: IntakeLinkStore, discardUnreadable = false): void {
  parseIntakeStore(JSON.stringify(store))
  let current: IntakeLinkStore | undefined
  try { current = readIntakeStore(storage) } catch {
    if (!discardUnreadable) throw new Error('Saved intake links could not be read. Re-import the workbook to review recovery options; nothing was overwritten.')
  }
  if (discardUnreadable ? !!current : JSON.stringify(current) !== JSON.stringify(expected)) {
    throw new Error('Saved intake links changed. Re-import the workbook before saving; nothing was overwritten.')
  }
  try { storage.setItem(INTAKE_STORAGE_KEY, JSON.stringify(store)) } catch {
    throw new Error('Intake links could not be saved. Browser storage may be full or disabled. Previous links and the roster are unchanged.')
  }
}

export function makeIntakeLink(year: number, person: Resident, slot: Resident): IntakeLink {
  return { year, slot_id: slot.slot_id!, mcr: person.mcr!, name: person.name!,
    postings: slot.postings.map(({ month, value, status, source }) => ({ month, value, status, source })) }
}

export async function applyIntakeLinks(workbook: Workbook, store: IntakeLinkStore, signal?: AbortSignal): Promise<Workbook> {
  let response: Response
  try {
    response = await fetch('/api/intake-links', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workbook, store }), signal: signal ?? AbortSignal.timeout(30_000) })
  } catch { throw new Error('Could not reach the backend for intake links. Check the connection and retry; the previous roster is unchanged.') }
  const data = await response.json().catch(() => null)
  if (!response.ok || !data || !Array.isArray(data.residents) || !Array.isArray(data.intake_links)) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Intake links could not be applied. Retry or re-import the workbook.')
  return data as Workbook
}
