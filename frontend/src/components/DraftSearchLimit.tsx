export default function DraftSearchLimit({ value, onChange, disabled }: {
  value: number; onChange: (seconds: number) => void; disabled: boolean
}) {
  return <label className="draft-search-limit"><span>Search limit</span>
    <span className="draft-search-value"><select aria-label="Maximum search time" value={value}
      disabled={disabled} onChange={(event) => onChange(Number(event.target.value))}>
      {[1, 2, 5, 10].map((minutes) => <option key={minutes} value={minutes * 60}>{minutes} min</option>)}
    </select><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg></span>
  </label>
}
