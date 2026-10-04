import { useQuery } from '@tanstack/react-query';
import { get } from '../api';
import { t } from '../i18n';

export type LlmOverride = { provider?: string; model?: string };
type Provider = { name: string; type?: string; default_model?: string | null };
type ProvidersDoc = {
  providers: Record<string, Provider>;
  tasks: Record<string, { provider?: string; model?: string }>;
};

export function effectiveRunLlm(task: string, value: LlmOverride | undefined, doc?: ProvidersDoc) {
  const taskDefault = doc?.tasks?.[task] ?? {};
  const providerId = value?.provider ?? taskDefault.provider ?? 'local';
  const provider = doc?.providers?.[providerId];
  return {
    providerId,
    providerName: provider?.name ?? providerId,
    model: value?.model || (value?.provider
      ? provider?.default_model
      : taskDefault.model || doc?.providers?.[providerId]?.default_model),
  };
}

export default function RunLlmSelector({ task, value, onChange, disabled }: {
  task: string; value?: LlmOverride; onChange: (value?: LlmOverride) => void; disabled?: boolean;
}) {
  const query = useQuery<ProvidersDoc>({ queryKey: ['providers'], queryFn: () => get('/api/providers') });
  const doc = query.data;
  const taskProviderId = doc?.tasks?.[task]?.provider ?? 'local';
  const effective = effectiveRunLlm(task, value, doc);
  const fallback = effectiveRunLlm(task, value?.provider ? { provider: value.provider } : undefined, doc);

  return <fieldset className="col run-llm-selector" disabled={disabled} style={{ border: '1px solid var(--border)', borderRadius: 8 }}>
    <legend>{t('run_llm.title')} · {t(`llm.task.${task}`)}</legend>
    <div className="row">
      <label className="col">{t('run_llm.connection')}
        <select aria-label={t('run_llm.connection')} value={value?.provider ?? ''} onChange={(e) => {
          const provider = e.target.value;
          onChange(provider ? { provider, model: '' } : undefined);
        }}>
          <option value="">{t('run_llm.task_default', { name: doc?.providers?.[taskProviderId]?.name ?? taskProviderId })}</option>
          {Object.entries(doc?.providers ?? {}).map(([id, provider]) => <option key={id} value={id}>{provider.name}</option>)}
        </select>
      </label>
      <label className="col grow">{t('run_llm.model')}
        <input aria-label={t('run_llm.model')} value={value?.model ?? ''} placeholder={t('run_llm.use_default', { model: fallback.model ?? '—' })}
          onChange={(e) => {
            const model = e.target.value;
            onChange(value?.provider ? { ...value, model } : (model ? { model } : undefined));
          }} />
      </label>
    </div>
    <span className="faint">{t('run_llm.effective', { connection: effective.providerName, model: effective.model ?? t('run_llm.not_configured') })}</span>
    <span className="faint">{t('run_llm.hint')}</span>
  </fieldset>;
}
