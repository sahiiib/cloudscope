import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { apiFetch, ApiError } from '../api/client';
import type { InstanceDetail } from '../api/types';
import Summary from './Summary';
import Tags from './Tags';
import Network from './Network';
import SecurityGroups from './SecurityGroups';
import RawJSON from './RawJSON';
import './details.css';

export default function InstanceDetails() {
  const { provider = '', account = '', region = '', id = '' } = useParams();
  const valid = ['aws', 'alibaba'].includes(provider) && !!account && !!region && !!id;
  const instance = useQuery({
    queryKey: ['instance', provider, account, region, id], enabled: valid,
    queryFn: async ({ signal }): Promise<InstanceDetail> => (await apiFetch(`/api/instances/${[provider, account, region, id].map(encodeURIComponent).join('/')}`, { signal })).json(),
    retry: false,
  });
  return <div className="instance-details"><Link to="/">Back to instances</Link><h1>Instance details</h1>
    {!valid || (instance.error instanceof ApiError && instance.error.status === 404) ? <p role="alert">Instance not found.</p>
      : instance.isPending ? <p role="status">Loading instance…</p>
      : <>
        {instance.isError && <p role="alert">Unable to {instance.data ? 'refresh' : 'load'} instance. <button onClick={() => void instance.refetch()}>Retry</button></p>}
        {instance.data && <div key={[provider, account, region, id].join('/')}>
          {!instance.data.present && <p className="missing-notice">Missing — this instance was not found on the last successful scan. The last observed data is shown below.</p>}
          <Summary instance={instance.data} /><Tags tags={instance.data.tags} /><Network instance={instance.data} />
          <SecurityGroups groups={instance.data.details?.security_groups} /><RawJSON raw={instance.data.raw} />
        </div>}
      </>}
  </div>;
}
