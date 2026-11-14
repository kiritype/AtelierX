import type { ReactNode } from 'react';
import { t } from '../../i18n';

export function GenerationDetails({ compact, summary, children, label }: {
  compact: boolean;
  label?: string;
  summary: (string | null | undefined)[];
  children: ReactNode;
}) {
  if (!compact) return <>{children}</>;
  return <details className="generation-details">
    <summary>
      <strong>{label ?? t('gen.advanced')}</strong>{' '}
      <span className="generation-details-summary faint small">{summary.filter(Boolean).join(' · ')}</span>
    </summary>
    <div className="col generation-details-content">{children}</div>
  </details>;
}
