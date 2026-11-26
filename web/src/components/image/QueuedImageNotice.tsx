import { useQuery } from '@tanstack/react-query';
import { get } from '../../api';
import { t } from '../../i18n';

export default function QueuedImageNotice() {
  const queue = useQuery<{ paused: boolean }>({
    queryKey: ['image-queue', 'pause-state'],
    queryFn: () => get('/api/image/queue?paused_only=true'),
    refetchInterval: 1500,
  });

  return queue.data?.paused ? <p className="faint small" role="status">{t('queue.waiting_while_paused')}</p> : null;
}
