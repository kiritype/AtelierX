import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { ApiError, get, post } from '../../api';
import { t, tm } from '../../i18n';
import type { ContentPack, ContentPreview, ContentStatus } from '../../imageTypes';
import ContentDialog from './ContentDialog';
import PresetModelsButton, { PresetModelsContent } from './PresetModels';
import './defaultContent.css';

type Kind = 'presets' | 'expressions';
type Choice = 'add' | 'replace' | 'copy' | 'skip';
const textOf = (e: unknown) => e instanceof ApiError ? tm(e.msg) : String(e);

export default function DefaultContent() {
  const qc = useQueryClient();
  const status = useQuery<ContentStatus>({ queryKey: ['default-content'], queryFn: () => get('/api/image/content/status') });
  const [kind, setKind] = useState<Kind | null>(null);
  const [packs, setPacks] = useState<ContentPack[]>([]);
  const [look, setLook] = useState<ContentPreview | null>(null);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState<{ written: string[]; kind: Kind; version: string } | null>(null);
  const active = useRef(0);
  async function load(which: Kind) {
    const request = ++active.current;
    setBusy(true); setError(''); setPacks([]); setLook(null); setDone(null);
    try {
      const result = await get<{ packs: ContentPack[] }>('/api/image/content/catalog');
      if (request !== active.current) return;
      const found = result.packs.filter(p => p.kind === which);
      setPacks(found);
      if (found.length === 1) await preview(found[0], request);
    } catch (e) { if (request === active.current) setError(textOf(e)); }
    finally { if (request === active.current) setBusy(false); }
  }
  async function preview(pack: ContentPack, request = active.current) {
    setBusy(true); setError('');
    try {
      const result = await post<ContentPreview>('/api/image/content/preview', { id: pack.id });
      if (request !== active.current) return;
      setLook(result);
      setChoices(Object.fromEntries(result.items.map(i => [i.key, i.state === 'new' ? 'add' : 'skip'])));
    } catch (e) { if (request === active.current) setError(textOf(e)); }
    finally { if (request === active.current) setBusy(false); }
  }
  const main = look?.items.filter(i => i.kind === kind) ?? [];
  const selected = main.filter(i => choices[i.key] !== 'skip');
  const dependencies = [...new Set(selected.flatMap(i => i.dependencies))];
  async function apply() {
    if (!look || !kind) return;
    const request = active.current;
    setBusy(true); setError('');
    try {
      const result = await post<{ written: string[]; kind: Kind; version: string }>('/api/image/content/import', { token: look.token, choices });
      qc.invalidateQueries({ queryKey: ['image-presets'] }); qc.invalidateQueries({ queryKey: ['image-lib'] });
      qc.invalidateQueries({ queryKey: ['default-content'] });
      if (request === active.current) setDone(result);
    } catch (e) { if (request === active.current) setError(textOf(e)); }
    finally { if (request === active.current) setBusy(false); }
  }
  function close() { ++active.current; setKind(null); }
  const itemRow = (item: ContentPreview['items'][number], dependency = false) => <div className="content-item" key={item.key}>
    {item.preview_url && <img className="content-thumb" src={item.preview_url} alt={item.name} />}
    <div className="col grow" style={{ gap: 6, minWidth: 0 }}>
      <div className="row" style={{ flexWrap: 'wrap' }}><strong>{item.name}</strong><span className="chip small">{t(`content.state.${item.state}`)}</span>
        {item.service && <span className="faint small">{item.service} · {item.family}</span>}</div>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {item.state === 'new' ? <label className="row"><input type="checkbox" disabled={busy} checked={choices[item.key] === 'add'} onChange={e => setChoices({ ...choices, [item.key]: e.target.checked ? 'add' : 'skip' })} />{t('content.include')}</label>
          : item.state === 'same' ? <span className="faint small">{t('content.keep_same')}</span>
          : <label className="row"><span className="small">{t('content.action')}</span><select disabled={busy} value={choices[item.key]} onChange={e => setChoices({ ...choices, [item.key]: e.target.value as Choice })}>
            <option value="skip">{t('content.keep')}</option><option value="copy">{t('content.copy')}</option><option value="replace">{t('content.replace')}</option>
          </select></label>}
        {dependency && <span className="faint small">{t('content.dependency')}</span>}
      </div>
      <details className="small"><summary>{t(item.before ? 'content.compare' : 'content.view')}</summary>
        <div className="content-diff">{item.before && <div><strong>{t('content.current')}</strong><pre>{JSON.stringify(item.before, null, 2)}</pre></div>}
          <div><strong>{t('content.incoming')}</strong><pre>{JSON.stringify(item.after, null, 2)}</pre></div></div>
      </details>
      {choices[item.key] === 'replace' && <p className="warn-text small">{t('content.replace_hint')}</p>}
    </div>
  </div>;
  const installedPresets = status.data?.installed.filter(p => p.kind === 'presets').flatMap(p => p.items) ?? [];
  return <section className="col" style={{ gap: 12 }}>
    <div className="section-title">{t('content.title')}</div><p className="faint">{t('content.about')}</p>
    <div className="content-cards">{(['presets', 'expressions'] as Kind[]).map(which => <div className="gen-patch col" style={{ gap: 8 }} key={which}>
      <strong>{t(`content.${which}.title`)}</strong><p className="faint small">{t(`content.${which}.description`)}</p>
      <span className="faint small">{status.data?.installed.filter(p => p.kind === which).map(p => `${p.version} · ${p.items.length}`).join(', ') || t('content.not_imported')}</span>
      <button onClick={() => { setKind(which); void load(which); }}>{t(`content.${which}.button`)}</button>
    </div>)}</div>
    {status.data && !status.data.configured && <p className="faint small">{t('content.not_configured')}</p>}
    {status.error && <p className="error" role="alert">{textOf(status.error)}</p>}
    {!!installedPresets.length && <div><PresetModelsButton ids={installedPresets} /></div>}
    {kind && <ContentDialog title={t(`content.${kind}.button`)} onClose={close} closeLabel={t(done ? 'content.finish' : 'common.cancel')}
      actions={look && !done && <button className="primary" disabled={busy || !selected.length} onClick={apply}>{t('content.import_selected', { n: selected.length })}</button>}>
      {busy && <p role="status">{t('content.loading')}</p>}
      {error && <div role="alert" className="col"><p className="error">{error}</p><button disabled={busy} onClick={() => load(kind)}>{t('content.retry')}</button></div>}
      {done ? <><p role="status" className="ok-text">{t('content.imported', { n: done.written.length, version: done.version })}</p>
        {done.kind === 'presets' && <PresetModelsContent ids={done.written} />}</>
        : <>{!look && !busy && !error && (packs.length ? <div className="col">{packs.map(pack => <button key={pack.id} onClick={() => preview(pack)}>{pack.title} · {pack.version}</button>)}</div> : <p>{t('content.empty')}</p>)}
          {look && <><p>{look.pack.title} · {look.pack.version}</p><p className="faint small">{look.pack.description}</p>
            <details className="small"><summary>{t('content.credits')}</summary><p>{look.pack.author}</p><p style={{ whiteSpace: 'pre-wrap' }}>{look.pack.license}</p></details>
            <p className="faint small">{t('content.global')}</p><button disabled={busy} onClick={() => setChoices(Object.fromEntries(look.items.map(i => [i.key, i.state === 'new' ? 'add' : 'skip'])))}>{t('content.select_new')}</button>
            <div className="content-list">{[...new Set(main.map(i => i.group))].map(group => <div key={group} className="col" style={{ gap: 8 }}>
              {kind === 'expressions' && <strong>{group || t('content.ungrouped')} · {main.filter(i => i.group === group).length}</strong>}
              {main.filter(i => i.group === group).map(i => itemRow(i))}
            </div>)}
              {!!dependencies.length && <details open><summary>{t('content.dependencies', { n: dependencies.length })}</summary>
                {look.items.filter(i => dependencies.includes(i.key)).map(i => itemRow(i, true))}</details>}
            </div></>}
        </>}
    </ContentDialog>}
  </section>;
}
