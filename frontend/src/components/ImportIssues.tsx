import type { ImportIssue } from '../lib/workbook'
import { groupIssuePostings, sourceLabel } from '../lib/workbook'

function IssueList({ issues }: { issues: ImportIssue[] }) {
  return <ul className="issue-list">{issues.map((issue, index) => <li key={index}>
    <details className="import-issue">
      <summary><span className="issue-copy"><strong>{issue.title || 'Import issue'}</strong><span>{issue.message}</span></span><svg className="issue-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg></summary>
      {issue.records ? <div className="table-scroll"><table className="issue-table"><caption className="sr-only">{issue.title || 'Recorded identities'}</caption><thead><tr><th scope="col">Recorded name</th><th scope="col">MCR</th><th scope="col">Source</th></tr></thead><tbody>{issue.records.map((record, row) => <tr key={row}><td>{record.name?.trim() ? record.name : 'Missing'}</td><td>{record.mcr?.trim() ? record.mcr : 'Missing'}</td><td>{sourceLabel(record.source)}</td></tr>)}</tbody></table></div>
        : issue.values ? <div className="table-scroll"><table className="issue-table"><caption className="sr-only">Recorded posting labels without a catalogue reference</caption><thead><tr><th scope="col">Recorded posting</th><th scope="col">Source</th></tr></thead><tbody>{groupIssuePostings(issue).map(({ value, sources }) => <tr key={value}><td>{value || 'Missing'}</td><td>{sources.length === 1 ? sourceLabel(sources[0]) : <details><summary>{sources.length} source locations</summary><ul>{sources.map((source, index) => <li key={index}>{sourceLabel(source)}</li>)}</ul></details>}</td></tr>)}</tbody></table></div>
          : <p className="source">{sourceLabel(issue.source)}</p>}
    </details>
  </li>)}</ul>
}

export default function ImportIssues({ issues, warnings }: { issues: ImportIssue[]; warnings: string[] }) {
  const count = issues.length + warnings.length
  return <>
    {count ? <><IssueList issues={issues} />{warnings.length > 0 && <ul className="issue-list">{warnings.map((warning, index) => <li className="workbook-warning" key={index}>{warning}</li>)}</ul>}</> : <p className="muted">No import issues were reported. Imported records still need programme review.</p>}
  </>
}
