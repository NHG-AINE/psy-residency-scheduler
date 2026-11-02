// React counterpart of preview/components.mjs workbook skeleton.
// Decorative shapes only; the owning region supplies its busy state and label.
export default function Skeleton() {
  return <div className="skeleton-content" aria-hidden="true">
    {[0, 1, 2].map((row) => <div className="loading-list-row" key={row}>
      <div className="loading-person"><span className="skeleton skeleton-file" /><div><span className="skeleton skeleton-title" /><span className="skeleton skeleton-small" /></div></div>
      <span className="skeleton skeleton-pill" />
    </div>)}
  </div>
}
