import type { SecurityGroup } from '../api/types';

export default function SecurityGroups({ groups }: { groups: SecurityGroup[] | null | undefined }) {
  return <section aria-labelledby="instance-security"><h2 id="instance-security">Security groups</h2>
    {!groups?.length ? <p>Not available</p> : groups.map(group => <article className="security-group" key={group.id}>
      <h3>{group.name ? `${group.name} · ${group.id}` : group.id}</h3><p>{group.description || 'Not available'}</p>
      {(['inbound', 'outbound'] as const).map(direction => <div key={direction}><h4>{direction === 'inbound' ? 'Inbound' : 'Outbound'}</h4>
        {group[direction] == null ? <p>Not available</p> : !group[direction].length ? <p>No rules</p> : <div className="detail-scroll"><table>
          <caption className="sr-only">{group.id} {direction} rules</caption>
          <thead><tr><th>Protocol</th><th>Ports / ICMP type/code</th><th>{direction === 'inbound' ? 'Source' : 'Destination'}</th><th>Description</th><th>Policy</th><th>Priority</th><th>Source ports</th></tr></thead>
          <tbody>{group[direction].map((rule, index) => <tr key={index}>
            <td>{rule.protocol === '-1' ? 'All' : rule.protocol || 'Not available'}</td><td>{rule.port_range || 'Not available'}</td>
            <td>{(direction === 'inbound' ? rule.source : rule.destination) || 'Not available'}</td><td>{rule.description || 'Not available'}</td>
            <td>{rule.policy || 'Not available'}</td><td>{rule.priority ?? 'Not available'}</td><td>{rule.source_port_range || 'Not available'}</td>
          </tr>)}</tbody>
        </table></div>}
      </div>)}
    </article>)}
  </section>;
}
