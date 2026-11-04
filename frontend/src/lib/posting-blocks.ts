import type { Resident } from './workbook'
import type { HistoryEntry } from './history-review.ts'
import { resolvedCatalogueTarget } from './history-review.ts'

export type PostingBlock = Resident['postings']
const monthIndex = (month: string) => Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7))

export function groupPostings(postings: Resident['postings']): PostingBlock[] {
  const blocks: PostingBlock[] = []
  for (const posting of postings) {
    const block = blocks[blocks.length - 1]
    const previous = block?.[block.length - 1]
    if (previous && previous.status === posting.status && previous.draft === posting.draft
      && (posting.status !== 'posting' || previous.value === posting.value)
      && monthIndex(posting.month) === monthIndex(previous.month) + 1) {
      block.push(posting)
    } else {
      blocks.push([posting])
    }
  }
  return blocks
}

export type PostingLabelMode = 'original' | 'catalogue'
export const DEFAULT_POSTING_LABEL_MODE: PostingLabelMode = 'catalogue'

export function postingDisplay(block: PostingBlock, mode: PostingLabelMode = DEFAULT_POSTING_LABEL_MODE, entries: HistoryEntry[] = []) {
  const status = block[0].status
  const original = status === 'loa' ? 'LOA' : status === 'blank' ? 'Unallocated' : block[0].value || 'Unallocated'
  if (block.every((posting) => posting.draft)) return { label: original, canonical: true, markers: [] as string[] }
  if (mode === 'original' || status !== 'posting') return { label: original, canonical: false, markers: [] as string[] }
  const targets = block.map((posting) => {
    const entry = entries.find((candidate) => candidate.months.some((month, index) => {
      const source = candidate.sources[index]
      return month.month === posting.month && month.value === posting.value
        && source?.sheet === posting.source.sheet && source.row === posting.source.row && source.column === posting.source.column
    }))
    return entry ? resolvedCatalogueTarget(entry.review) : null
  })
  const target = targets[0]
  if (!target || targets.some((candidate) => candidate?.key !== target.key || candidate.signature !== target.signature)) {
    return { label: original, canonical: false, markers: [] as string[] }
  }
  const markers = []
  if (target.category === 'elective') markers.push('Elective')
  if (/\bremediation\b/i.test(block[0].value || '')) markers.push('Remediation')
  return { label: target.label, canonical: true, markers }
}

export function postingCategory(display: ReturnType<typeof postingDisplay>, status: Resident['postings'][number]['status']) {
  if (status === 'loa') return 'loa'
  if (status === 'blank') return 'unallocated'
  if (!display.canonical) return 'unresolved'
  return display.markers.includes('Elective') ? 'elective' : 'core'
}
