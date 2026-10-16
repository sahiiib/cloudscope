import type { AccountRegion } from '../api/types';

export default function RegionPicker({ regions, excluded, onChange, error }: {
  regions: AccountRegion[]; excluded: string[]; onChange: (region: string, scan: boolean) => void; error?: string;
}) {
  return <fieldset><legend>Regions to scan</legend>
    {regions.length === 0 && <small>Click Select regions to discover this account’s regions.</small>}
    <div className="region-checklist">{regions.map(item => <label className="settings-check" key={item.region}>
      <input type="checkbox" aria-label={`Scan ${item.region}`} checked={!excluded.includes(item.region)} onChange={event => onChange(item.region, event.target.checked)} />
      <span>{item.region} · {item.instances} instances · {item.load_balancers} load balancers</span>
    </label>)}</div>
    {error && <p role="alert" className="error">{error}</p>}
  </fieldset>;
}
