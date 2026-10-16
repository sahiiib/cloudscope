import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { InstanceSummary } from '../api/types';
import { CopyIcon, OtherStateIcon, RunningIcon, StoppedIcon, TerminatedIcon } from '../icons';

const stateIcons = { running: RunningIcon, stopped: StoppedIcon, terminated: TerminatedIcon } as const;

function StateIcon({ state }: { state: string }) {
  const known = state in stateIcons ? state as keyof typeof stateIcons : null;
  const Glyph = known ? stateIcons[known] : OtherStateIcon;
  return <span className={`state-icon state-${known ?? 'other'}`} role="img" aria-label={state} title={state}><Glyph /></span>;
}

function launchAge(value: string) {
  const days = Math.floor((Date.now() - Date.parse(value)) / 86400000);
  return new Intl.RelativeTimeFormat('en', { numeric: 'auto' }).format(-days, 'day');
}

export default function InstanceTable({ items, sort, onSort }: {
  items: InstanceSummary[]; sort: string; onSort: (field: string) => void;
}) {
  const navigate = useNavigate();
  const [copyStatus, setCopyStatus] = useState('');
  function heading(label: string, field: string) {
    const active = sort.replace(/^-/, '') === field;
    return <th scope="col" aria-sort={active ? (sort.startsWith('-') ? 'descending' : 'ascending') : 'none'}>
      <button className="secondary" onClick={() => onSort(field)}>{label}{active ? (sort.startsWith('-') ? ' ↓' : ' ↑') : ''}</button>
    </th>;
  }
  return <><p role="status">{copyStatus}</p><div className="instance-scroll"><table className="instance-table">
    <thead><tr>{heading('Name', 'name')}<th scope="col">Instance ID</th><th scope="col">State</th><th scope="col">Type</th>
      <th scope="col">Private IPs</th><th scope="col">Public IPs</th>{heading('Account', 'account')}<th scope="col">Account alias</th><th scope="col">Account ID</th>{heading('Region', 'region')}
      <th scope="col">Provider</th>{heading('Launch time', 'launch_time')}<th scope="col">Tags</th></tr></thead>
    <tbody>{items.map(item => {
      const path = '/instances/' + [item.provider, item.account_id, item.region, item.instance_id].map(encodeURIComponent).join('/');
      const tags = Object.entries(item.tags);
      return <tr key={path} onClick={event => {
        if (!(event.target as HTMLElement).closest('a, button') && !window.getSelection()?.toString()) navigate(path);
      }}>
        <td><Link to={path}>{item.name || 'Unnamed instance'}</Link>{!item.present && <small>Missing</small>}</td>
        <td><code>{item.instance_id}</code> <button aria-label={`Copy ${item.instance_id}`} onClick={async () => {
          try { await navigator.clipboard.writeText(item.instance_id); setCopyStatus('Instance ID copied.'); }
          catch { setCopyStatus('Unable to copy. Select and copy the instance ID.'); }
        }} title="Copy instance ID" className="secondary icon-button"><CopyIcon /></button></td>
        <td><StateIcon state={item.state} /></td>
        <td>{item.instance_type}</td><td>{item.private_ips.join(', ') || '—'}</td><td>{item.public_ips.join(', ') || '—'}</td>
        <td>{item.account_name}</td><td>{item.account_alias ?? '–'}</td>
        <td><code>{item.account_id}</code> <button aria-label={`Copy account ID ${item.account_id}`} onClick={async () => {
          try { await navigator.clipboard.writeText(item.account_id); setCopyStatus('Account ID copied.'); }
          catch { setCopyStatus('Unable to copy. Select and copy the account ID.'); }
        }} title="Copy account ID" className="secondary icon-button"><CopyIcon /></button></td><td>{item.region}</td><td>{item.provider === 'aws' ? 'AWS' : 'Alibaba'}</td>
        <td>{item.launch_time ? <time dateTime={item.launch_time} title={new Date(item.launch_time).toISOString()}>{launchAge(item.launch_time)}</time> : '—'}</td>
        <td>{tags.slice(0, 3).map(([key, value]) => <span className="tag-chip" key={key}>{key}={value}</span>)}
          {tags.length > 3 && <span title={tags.slice(3).map(([key, value]) => `${key}=${value}`).join('\n')}>+{tags.length - 3}</span>}
          {!tags.length && '—'}</td>
      </tr>;
    })}</tbody>
  </table></div></>;
}
