import type { ReactNode } from 'react';
import { t } from '../../i18n';

export function GenerationDetails({ compact, summary, children }: {
  compact: boolean;
  summary: (string | null | undefined)[];
  children: ReactNode;
}) {
  if (!compact) return <>{children}</>;
  return <details className="generation-details">
    <summary>
      <strong>{t('gen.advanced')}</strong>{' '}
      <span className="generation-details-summary faint small">{summary.filter(Boolean).join(' · ')}</span>
    </summary>
    <div className="col generation-details-content">{children}</div>
  </details>;
}
