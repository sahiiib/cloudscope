import { Link } from 'react-router-dom';
import type { ElasticIPSummary } from '../api/types';
import CopyButton from '../CopyButton';
export default function Association({ association, onStatus }: { association: ElasticIPSummary['association']; onStatus: (status: string) => void }) {
  if (!association) return <>Not associated</>;
  const text = `${association.type || 'unknown'} · ${association.id || 'unknown'}`;
  return <>{association.link ? <Link to={association.link}>{text}</Link> : <span>{text}</span>}
    {association.id && <CopyButton value={association.id} label={`Copy associated ID ${association.id}`} what="Associated ID" onStatus={onStatus} />}</>;
}
