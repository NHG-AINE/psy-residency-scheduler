import { useState } from 'react'
import type { Source, Workbook } from '../lib/workbook'
import { matchesPostingReference, postingReferenceYears, sourceLabel } from '../lib/workbook'
import SearchField from './SearchField'

type Category = 'Core' | 'Electives'
const categories: Category[] = ['Core', 'Electives']
const show = (value: string | null | undefined) => value || '\u2014'
const source = (value: Source) => <small className="source">{sourceLabel(value)}</small>

export default function PostingReference({ workbook }: { workbook: Workbook }) {
  const [category, setCategory] = useState<Category>('Core')
  const [year, setYear] = useState('')
  const [query, setQuery] = useState('')
  const corePostings = workbook.postings.core.filter((posting) => [posting.posting, posting.duration_months, posting.max, posting.remarks].some((value) => value?.trim()))
  const electives = workbook.postings.electives || []
  const years = postingReferenceYears(category === 'Core' ? corePostings : electives)
  const filteredCore = corePostings.filter((posting) => matchesPostingReference(posting, year, query))
  const filteredElectives = electives.filter((posting) => matchesPostingReference(posting, year, query))
  function selectCategory(next: Category) {
    setCategory(next)
    if (!postingReferenceYears(next === 'Core' ? corePostings : electives).includes(year)) setYear('')
  }
  return <div className="review-content"><h2>Posting reference</h2>
    <div className="view-nav posting-tabs" role="tablist" aria-label="Posting references">{categories.map((item, index) => <button key={item} type="button" role="tab" id={`postings-${item}`} aria-controls="posting-reference-panel" aria-selected={category === item} tabIndex={category === item ? 0 : -1} className={category === item ? 'active' : ''} onClick={() => selectCategory(item)} onKeyDown={(event) => {
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? categories.length - 1 : event.key === 'ArrowRight' ? (index + 1) % categories.length : event.key === 'ArrowLeft' ? (index + categories.length - 1) % categories.length : -1
      if (next < 0) return
      event.preventDefault()
      selectCategory(categories[next])
      document.getElementById(`postings-${categories[next]}`)?.focus()
    }}>{item}</button>)}</div>
    <div className="posting-filters">
      <label>Residency year<select value={year} onChange={(event) => setYear(event.target.value)}><option value="">All years</option>{years.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <SearchField id="posting-search" label="Search postings" placeholder="Posting name" value={query} onChange={setQuery} />
    </div>
    <div id="posting-reference-panel" role="tabpanel" aria-labelledby={`postings-${category}`} tabIndex={0}>
      <p className="muted posting-reference-note">{category === 'Core' ? 'Reference values recorded in the workbook. Blank capacity means unknown.' : 'Elective departments and notes recorded in the workbook.'}</p>
      {category === 'Core' ? (
        filteredCore.length ? <div className="table-scroll"><table><caption className="sr-only">Core posting reference</caption><thead><tr><th scope="col">Residency year</th><th scope="col">Posting</th><th scope="col">Duration (months)</th><th scope="col">Maximum</th><th scope="col">Remarks / source</th></tr></thead><tbody>{filteredCore.map((posting, index) => <tr key={index}><td>{show(posting.residency_year)}</td><td>{show(posting.posting)}</td><td>{show(posting.duration_months)}</td><td>{show(posting.max)}</td><td>{show(posting.remarks)}{source(posting.source)}</td></tr>)}</tbody></table></div> : <p className="empty-note">{corePostings.length ? 'No core postings match these filters.' : 'No core posting reference was found.'}</p>
      ) : (
        filteredElectives.length ? <div className="table-scroll"><table className="elective-catalogue"><caption className="sr-only">Elective catalogue</caption><thead><tr><th scope="col">Residency year</th><th scope="col">Institution</th><th scope="col">Elective</th><th scope="col">Remarks / source</th></tr></thead><tbody>{filteredElectives.map((elective, index) => <tr key={index}><td>{elective.residency_year}</td><td>{elective.institution}</td><td>{elective.elective}</td><td>{elective.remarks.length ? elective.remarks.map((remark, index) => <div className="elective-remark" key={index}>{remark.text}</div>) : show(null)}{source({ sheet: elective.source.sheet, row: elective.source.row })}</td></tr>)}</tbody></table></div> : <p className="empty-note">{electives.length ? 'No electives match these filters.' : 'No elective catalogue was found.'}</p>
      )}
    </div>
  </div>
}
