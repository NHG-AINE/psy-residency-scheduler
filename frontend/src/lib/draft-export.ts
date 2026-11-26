import type { DraftSchedule } from './draft-schedule'
import type { ReviewStore } from './history-review'

async function requestExport(path: string, form: FormData, signal?: AbortSignal) {
  let response: Response
  try {
    const timeout = AbortSignal.timeout(60_000)
    response = await fetch(path, { method: 'POST', body: form, signal: signal ? AbortSignal.any([signal, timeout]) : timeout })
  } catch {
    throw new Error('Could not export Excel. Check the connection and retry.')
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'Excel export failed. Retry.')
  }
  return response
}

export async function exportCurrentWorkbook(file: File, targetYear: number, draft: DraftSchedule | null, signal?: AbortSignal): Promise<{ blob: Blob; retainedResidents: string[] }> {
  if (!draft) return { blob: file, retainedResidents: [] }
  const form = new FormData()
  form.append('originalFile', file)
  form.append('target_year', String(targetYear))
  form.append('draft', JSON.stringify({ ...draft, edit_baseline: undefined }))
  const response = await requestExport('/api/export', form, signal)
  const retained: unknown = JSON.parse(response.headers.get('X-Export-Retained-Residents') || '[]')
  if (!Array.isArray(retained) || !retained.every((name) => typeof name === 'string')) throw new Error('Excel export warnings could not be read. Retry.')
  return { blob: await response.blob(), retainedResidents: retained }
}

export async function prepareNextWorkbook(file: File, targetYear: number, store: ReviewStore, draft: DraftSchedule | null, signal?: AbortSignal) {
  const form = new FormData()
  form.append('originalFile', file)
  form.append('target_year', String(targetYear))
  form.append('store', JSON.stringify(store))
  if (draft) form.append('draft', JSON.stringify({ ...draft, edit_baseline: undefined }))
  const response = await requestExport('/api/export/prepare-next-year', form, signal)
  return response.blob()
}

export function downloadWorkbook(blob: Blob, originalName: string, targetYear?: number, kind: 'Draft' | 'Prepared' = 'Draft') {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = targetYear === undefined ? originalName : `${originalName.replace(/\.xlsx$/i, '')} - ${kind} ${targetYear}-${targetYear + 1}.xlsx`
  try {
    document.body.append(link)
    link.click()
  } finally {
    link.remove()
    // Let the browser consume the object URL before releasing it.
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
