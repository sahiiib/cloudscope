import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { InstanceSummary } from '../api/types';
import FloatingScroll from '../FloatingScroll';
import CopyButton from '../CopyButton';
import { StateIcon } from '../icons';

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
  function ips(values: string[], what: string) {
    if (!values.length) return '—';
    return values.map(ip => <div className="copy-line" key={ip}><code>{ip}</code> <CopyButton value={ip} label={`Copy ${what.charAt(0).toLowerCase() + what.slice(1)} ${ip}`} what={what} onStatus={setCopyStatus} /></div>);
  }
  return <><p role="status">{copyStatus}</p><FloatingScroll className="instance-scroll"><table className="instance-table">
    <thead><tr>{heading('Name', 'name')}<th scope="col">Instance ID</th><th scope="col">State</th><th scope="col">Type</th>
      <th scope="col">Private IPs</th><th scope="col">Public IPs</th>{heading('Account', 'account')}<th scope="col">Account alias</th><th scope="col">Account ID</th>{heading('Region', 'region')}
      <th scope="col">Provider</th>{heading('Launch time', 'launch_time')}<th scope="col">Tags</th></tr></thead>
    <tbody>{items.map(item => {
      const path = '/instances/' + [item.provider, item.account_id, item.region, item.instance_id].map(encodeURIComponent).join('/');
      const tags = Object.entries(item.tags);
      return <tr key={path} onClick={event => {
        if (!(event.target as HTMLElement).closest('a, button') && !window.getSelection()?.toString()) navigate(path);
      }}>
        <td className="copy-line"><Link to={path}>{item.name || 'Unnamed instance'}</Link>{item.name && <> <CopyButton value={item.name} label={`Copy name ${item.name}`} what="Name" onStatus={setCopyStatus} /></>}{!item.present && <small>Missing</small>}</td>
        <td className="copy-line"><code>{item.instance_id}</code> <CopyButton value={item.instance_id} label={`Copy ${item.instance_id}`} what="Instance ID" onStatus={setCopyStatus} /></td>
        <td><StateIcon state={item.state} /></td>
        <td>{item.instance_type}</td><td>{ips(item.private_ips, 'Private IP')}</td><td>{ips(item.public_ips, 'Public IP')}</td>
        <td>{item.account_name}</td><td>{item.account_alias ?? '–'}</td>
        <td className="copy-line"><code>{item.account_id}</code> <CopyButton value={item.account_id} label={`Copy account ID ${item.account_id}`} what="Account ID" onStatus={setCopyStatus} /></td><td>{item.region}</td><td>{item.provider === 'aws' ? 'AWS' : 'Alibaba'}</td>
        <td>{item.launch_time ? <time dateTime={item.launch_time} title={new Date(item.launch_time).toISOString()}>{launchAge(item.launch_time)}</time> : '—'}</td>
        <td>{tags.slice(0, 3).map(([key, value]) => <span className="tag-chip" key={key}>{key}={value}</span>)}
          {tags.length > 3 && <span title={tags.slice(3).map(([key, value]) => `${key}=${value}`).join('\n')}>+{tags.length - 3}</span>}
          {!tags.length && '—'}</td>
      </tr>;
    })}</tbody>
  </table></FloatingScroll></>;
}
