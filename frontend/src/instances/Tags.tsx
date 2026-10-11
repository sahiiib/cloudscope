export default function Tags({ tags }: { tags: Record<string, string> | null }) {
  const entries = Object.entries(tags ?? {});
  return <section aria-labelledby="instance-tags"><h2 id="instance-tags">Tags</h2>
    {!entries.length ? <p>Not available</p> : <table><caption className="sr-only">Instance tags</caption><thead><tr><th>Key</th><th>Value</th></tr></thead>
      <tbody>{entries.map(([key, value]) => <tr key={key}><td>{key}</td><td>{value}</td></tr>)}</tbody></table>}
  </section>;
}
