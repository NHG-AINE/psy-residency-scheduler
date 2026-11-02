import type { Resident } from './workbook'

export type PostingBlock = Resident['postings']
const monthIndex = (month: string) => Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7))

export function groupPostings(postings: Resident['postings']): PostingBlock[] {
  const blocks: PostingBlock[] = []
  for (const posting of postings) {
    const block = blocks[blocks.length - 1]
    const previous = block?.[block.length - 1]
    if (previous && previous.status === posting.status
      && (posting.status !== 'posting' || previous.value === posting.value)
      && monthIndex(posting.month) === monthIndex(previous.month) + 1) {
      block.push(posting)
    } else {
      blocks.push([posting])
    }
  }
  return blocks
}
