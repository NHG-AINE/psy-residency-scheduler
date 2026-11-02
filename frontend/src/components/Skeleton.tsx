// Decorative timetable placeholders; the owning region supplies its busy state and label.
export default function Skeleton() {
  return <div className="table-scroll timetable" aria-hidden="true">
    <table>
      <colgroup><col className="resident-column" />{Array.from({ length: 12 }, (_, month) => <col key={month} />)}</colgroup>
      <thead><tr><th><span className="skeleton skeleton-title" /></th>{Array.from({ length: 12 }, (_, month) => <th key={month}><span className="skeleton skeleton-month" /></th>)}</tr></thead>
      <tbody>{Array.from({ length: 7 }, (_, row) => <tr key={row}>
        <th scope="row"><span className="skeleton skeleton-name" /><span className="skeleton skeleton-meta" /></th>
        <td colSpan={12}><span className="skeleton skeleton-posting" /></td>
      </tr>)}</tbody>
    </table>
  </div>
}
