import type { DraftSchedule } from './draft-schedule'

export async function exportDraft(file: File, targetYear: number, draft: DraftSchedule, signal?: AbortSignal): Promise<{ blob: Blob; retainedResidents: string[] }> {
  const form = new FormData()
  form.append('originalFile', file)
  form.append('target_year', String(targetYear))
  form.append('draft', JSON.stringify({ ...draft, edit_baseline: undefined }))
  let response: Response
  try {
    response = await fetch('/api/export', { method: 'POST', body: form, signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(60_000)]) : AbortSignal.timeout(60_000) })
  } catch {
    throw new Error('Could not export Excel. Check the connection and retry.')
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'Excel export failed. Retry.')
  }
  const retained: unknown = JSON.parse(response.headers.get('X-Export-Retained-Residents') || '[]')
  if (!Array.isArray(retained) || !retained.every((name) => typeof name === 'string')) throw new Error('Excel export warnings could not be read. Retry.')
  return { blob: await response.blob(), retainedResidents: retained }
}

export function downloadDraft(blob: Blob, originalName: string, targetYear: number) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${originalName.replace(/\.xlsx$/i, '')} - Draft ${targetYear}-${targetYear + 1}.xlsx`
  try {
    document.body.append(link)
    link.click()
  } finally {
    link.remove()
    // Let the browser consume the object URL before releasing it.
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
