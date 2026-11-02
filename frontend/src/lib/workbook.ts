export type Source = { sheet: string; row: number; column?: string }
export type Month = { month: string; date_range_text: string | null; source: Source }
export type Resident = {
  name: string | null; mcr: string | null; residency_year: string | null
  intake: string | null; mom_number: string | null; email: string | null
  remarks: string | null; source: Source
  match_status?: 'matched' | 'unmatched' | 'ambiguous'; matched_resident_source?: Source | null
  postings: { month: string; value: string | null; source: Source }[]
}
export type Request = {
  name: string | null; mcr: string | null; email: string | null; intake: string | null
  residency_year: string | null; posting_request: string | null; period: string | null
  remarks: string | null; source: Source
  match_status?: 'matched' | 'unmatched' | 'ambiguous'; matched_resident_source?: Source | null
}
export type Workbook = {
  target_year: number; available_years: { year: number; sheet: string }[]
  target_sheet: string | null; months: Month[]; residents: Resident[]
  histories: { year: number; sheet: string; months: Month[]; residents: Resident[] }[]
  requests: Request[]
  postings: {
    core: { residency_year: string | null; posting: string | null; duration_months: string | null; max: string | null; remarks: string | null; source: Source }[]
    rows: { source: Source; cells: Record<string, string | null> }[]
  }
  warnings: string[]
  issues?: { code: string; severity: 'warning' | 'info'; message: string; source: Source; values?: string[]; sources?: Source[] }[]
}

export function workbookError(files: Pick<File, 'name' | 'size'>[]): string {
  if (files.length !== 1) return 'Choose one workbook at a time.'
  if (!/\.xlsx$/i.test(files[0].name)) return 'Choose an Excel workbook ending in .xlsx.'
  if (!files[0].size) return 'This file is empty. Choose a workbook with content.'
  if (files[0].size > 10 * 1024 * 1024) return 'Choose a workbook of 10 MB or smaller.'
  return ''
}

export async function importWorkbook(file: File, year: number): Promise<Workbook> {
  const body = new FormData()
  body.append('file', file)
  body.append('target_year', String(year))
  let response: Response
  try {
    response = await fetch('/api/import', { method: 'POST', body, signal: AbortSignal.timeout(30_000) })
  } catch (error: unknown) {
    if (error instanceof DOMException && (error.name === 'TimeoutError' || error.name === 'AbortError')) {
      throw new Error('Workbook import timed out. Check the backend connection and try again.')
    }
    throw new Error('Could not reach the backend. Check the connection and try again.')
  }
  let result: unknown
  try { result = await response.json() } catch {
    throw new Error('The backend did not return valid JSON. Check the connection and try again.')
  }
  if (!response.ok) {
    const detail = (result as { detail?: unknown })?.detail
    throw new Error(typeof detail === 'string' ? detail : `Workbook import failed (HTTP ${response.status}). Choose a supported workbook and try again.`)
  }
  const workbook = result as Workbook | null
  if (!workbook || typeof workbook !== 'object' || !Number.isInteger(workbook.target_year)
    || ![workbook.residents, workbook.available_years, workbook.months, workbook.histories, workbook.requests, workbook.warnings, workbook.postings?.core, workbook.postings?.rows].every(Array.isArray)) {
    throw new Error('The backend returned an unexpected workbook response. Check the connection and try again.')
  }
  return result as Workbook
}

export function sourceLabel(source: Source): string {
  return `${source.sheet} · ${source.column ? `${source.column}${source.row}` : `row ${source.row}`}`
}

export function monthLabel(month: string): string {
  return new Date(`${month}-01T00:00:00Z`).toLocaleDateString('en-SG', { month: 'short', year: '2-digit', timeZone: 'UTC' })
}
