type Props = {
  id: string; label: string; placeholder: string; value: string
  onChange: (value: string) => void; disabled?: boolean
}

export default function SearchField({ id, label, placeholder, value, onChange, disabled }: Props) {
  return <div className="search-field"><label htmlFor={id}>{label}</label><input id={id} type="search" placeholder={placeholder} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} /></div>
}
