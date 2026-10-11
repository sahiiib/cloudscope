import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { InstanceSummary } from '../api/types';

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
      <th scope="col">Private IPs</th><th scope="col">Public IPs</th>{heading('Account', 'account')}{heading('Region', 'region')}
      <th scope="col">Provider</th>{heading('Launch time', 'launch_time')}<th scope="col">Tags</th></tr></thead>
    <tbody>{items.map(item => {
      const path = '/instances/' + [item.provider, item.account_id, item.region, item.instance_id].map(encodeURIComponent).join('/');
      const tags = Object.entries(item.tags);
      return <tr key={path} onClick={event => {
        if (!(event.target as HTMLElement).closest('a, button') && !window.getSelection()?.toString()) navigate(path);
      }}>
        <td><Link to={path}>{item.name || 'Unnamed instance'}</Link>{!item.present && <small>Missing</small>}</td>
        <td><code>{item.instance_id}</code> <button className="secondary" aria-label={`Copy ${item.instance_id}`} onClick={async () => {
          try { await navigator.clipboard.writeText(item.instance_id); setCopyStatus('Instance ID copied.'); }
          catch { setCopyStatus('Unable to copy. Select and copy the instance ID.'); }
        }}>Copy</button></td>
        <td><span className={`state-badge state-${['running', 'stopped', 'terminated'].includes(item.state) ? item.state : 'other'}`}>{item.state}</span></td>
        <td>{item.instance_type}</td><td>{item.private_ips.join(', ') || '—'}</td><td>{item.public_ips.join(', ') || '—'}</td>
        <td>{item.account_name}<small>{item.account_id}</small></td><td>{item.region}</td><td>{item.provider === 'aws' ? 'AWS' : 'Alibaba'}</td>
        <td>{item.launch_time ? <time dateTime={item.launch_time} title={new Date(item.launch_time).toISOString()}>{launchAge(item.launch_time)}</time> : '—'}</td>
        <td>{tags.slice(0, 3).map(([key, value]) => <span className="tag-chip" key={key}>{key}={value}</span>)}
          {tags.length > 3 && <span title={tags.slice(3).map(([key, value]) => `${key}=${value}`).join('\n')}>+{tags.length - 3}</span>}
          {!tags.length && '—'}</td>
      </tr>;
    })}</tbody>
  </table></div></>;
}
