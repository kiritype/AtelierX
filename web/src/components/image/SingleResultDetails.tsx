import { t } from '../../i18n';
import type { SingleRun, SingleService } from '../../imageTypes';
import { SERVICE_NAMES } from './serviceSettings';
import { resultSeed, resultSettings, resultSource, settingDifferences, type ResultPromptSource, type SingleInput } from './singleResult';
import './SingleResultDetails.css';

const serviceName = (service: SingleService) => SERVICE_NAMES[service] ?? service;
const display = (value: unknown, missing = t('single.result_missing')) => {
  if (value === undefined) return missing;
  if (value === null || value === '') return t('single.result_empty');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
};
const settingLabels: Record<string, string> = {
  model: 'gen.model', width: 'gen.width', height: 'gen.height', size: 'pixai.size',
  aspect_ratio: 'pixai.aspect_ratio', seed: 'gen.seed', steps: 'gen.steps',
  sampler: 'gen.sampler', scheduler: 'gen.scheduler', family: 'gen.family',
  cfg: 'single.result_cfg', cfg_scale: 'single.result_cfg', scale: 'single.result_cfg',
};

export default function SingleResultDetails({ run, current, restoredSources = [], busy, handoffPending, restore, regenerate, handoff }: {
  run: SingleRun;
  current: SingleInput;
  restoredSources?: ResultPromptSource[];
  busy: boolean;
  handoffPending: boolean;
  restore: () => void;
  regenerate: (newSeed: boolean) => void;
  handoff: (target: 'tools' | 'lab') => void;
}) {
  const actual = run.actual;
  const settings = actual?.settings ?? {};
  const seed = resultSeed(run);
  const size = settings.width != null && settings.height != null
    ? `${settings.width} × ${settings.height}`
    : settings.size;
  const cfg = settings[run.service === 'novelai' ? 'scale' : run.service === 'pixai' ? 'cfg_scale' : 'cfg'];
  const summary = [
    [t('gen.service'), run.service ? serviceName(run.service) : undefined],
    [t('gen.model'), settings.model],
    [t('single.result_size'), size],
    ...(run.service === 'pixai' ? [[t('pixai.aspect_ratio'), settings.aspect_ratio]] : []),
    [t('single.result_composition'), resultSource(run, 'composition')],
    [t('single.preset'), resultSource(run, 'style')],
    [t('gen.seed'), seed],
    [t('gen.steps'), settings.steps],
    [t('single.result_cfg'), cfg],
    [t('gen.sampler'), settings.sampler],
  ];
  const currentSources = current.sources ?? [];
  const sourcesChanged = settingDifferences({ sources: currentSources }, { sources: restoredSources }).length > 0;
  const sourceText = (sources: ResultPromptSource[]) => sources.map(source => [source.name, source.positive, source.negative]
    .filter(Boolean).join(' · ')).join('\n');
  const diffs = actual ? [
    ...settingDifferences({ service: current.service, positive: current.positive, negative: current.negative },
      { service: run.service, positive: actual.positive, negative: actual.negative }).map(row => ({
        ...row, label: t(row.key === 'service' ? 'gen.service' : `single.${row.key}`),
        current: row.key === 'service' ? serviceName(current.service) : row.current,
        result: row.key === 'service' ? serviceName(run.service) : row.result,
      })),
    ...(sourcesChanged ? [{
      key: 'sources', label: t('single.result_sources'), current: sourceText(currentSources), result: sourceText(restoredSources),
    }] : []),
    ...settingDifferences(current.settings, resultSettings(run)).map(row => ({
      ...row, key: `setting:${row.key}`, label: settingLabels[row.key] ? t(settingLabels[row.key]) : row.key,
    })),
  ] : [];
  const cannotRestore = busy || !actual || !run.service;
  const cannotGenerate = cannotRestore || !actual?.positive.trim();
  const compareReason = run.service !== 'comfyui' ? 'single.compare_comfy_only'
    : !run.path ? 'single.result_no_file' : !actual ? 'single.result_no_settings' : '';

  return <div className="single-result-details">
    <h4>{t('single.result_summary')}</h4>
    <dl className="single-result-summary">{summary.map(([label, value]) => <div key={String(label)}>
      <dt>{String(label)}</dt><dd>{display(value)}</dd>
    </div>)}</dl>
    {actual && <details className="single-details">
      <summary tabIndex={0}>{t('single.result_diff')}</summary>
      <p className="faint small">{t('single.result_restore_note')}</p>
      {diffs.length ? <table className="single-result-diff">
        <thead><tr><th scope="col">{t('single.result_field')}</th><th scope="col">{t('single.result_current')}</th>
          <th scope="col">{t('single.result_recorded')}</th></tr></thead>
        <tbody>{diffs.map(row => <tr key={row.key}>
          <th scope="row">{row.label}</th>
          <td>{display(row.current, t('single.result_unset'))}</td>
          <td>{display(row.result)}</td>
        </tr>)}</tbody>
      </table> : <p className="faint small">{t('single.result_no_diff')}</p>}
    </details>}
    <div className="single-result-group" role="group" aria-label={t('single.result_retry_group')}>
      <h4>{t('single.result_retry_group')}</h4>
      <div className="single-result-actions">
        <button type="button" disabled={cannotRestore} onClick={restore}>{t('single.restore')}</button>
        <button type="button" disabled={cannotGenerate || seed === undefined} onClick={() => regenerate(false)}>{t('single.regenerate')}</button>
        <button type="button" disabled={cannotGenerate} onClick={() => regenerate(true)}>{t('single.result_new_seed')}</button>
      </div>
      <p className="faint small">{!actual ? t('single.result_no_settings') : busy ? t('single.result_busy')
        : !run.service ? t('single.result_no_service') : !actual.positive.trim() ? t('single.result_no_prompt') : seed === undefined ? t('single.result_no_seed') : t('single.result_seed_note')}</p>
    </div>
    <div className="single-result-group" role="group" aria-label={t('single.result_next_group')}>
      <h4>{t('single.result_next_group')}</h4>
      <div className="single-result-actions">
        <button type="button" disabled={Boolean(compareReason) || handoffPending} onClick={() => handoff('lab')}>{t('single.compare')}</button>
        <button type="button" disabled={!run.path || handoffPending} onClick={() => handoff('tools')}>{t('single.send_tools')}</button>
      </div>
      {compareReason && <p className="faint small">{t(compareReason)}</p>}
      {!run.path && compareReason !== 'single.result_no_file' && <p className="faint small">{t('single.result_no_file')}</p>}
    </div>
    {actual && <details className="single-details"><summary tabIndex={0}>{t('single.result_settings')}</summary>
      <pre>{JSON.stringify(actual, null, 2)}</pre>
    </details>}
  </div>;
}
