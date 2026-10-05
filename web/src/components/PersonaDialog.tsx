import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get, put } from '../api';
import { t, tm } from '../i18n';
import { useToast } from './Toasts';
import { Dialog } from './ui';

// Personas ({{user}} of the test chat, 08-chat-test): one list for the whole app (data/personas.json); which one a
// work uses is screen state (state/ui.json → persona_by_work), so it never goes into the work's files.

export type Persona = { id: string; name: string; description: string; updated_at?: string };
type PersonaList = { personas: Persona[]; revision: string };

const utf8 = (text: string) => new TextEncoder().encode(text).length;

export function usePersona(workId: string) {
  const qc = useQueryClient();
  const list = useQuery<PersonaList>({ queryKey: ['personas'], queryFn: () => get('/api/personas') });
  const ui = useQuery<Record<string, any>>({ queryKey: ['ui-state'], queryFn: () => get('/api/ui-state') });
  const selectedId: string | null = ui.data?.persona_by_work?.[workId] ?? null;
  const persona = list.data?.personas.find((p) => p.id === selectedId) ?? null;
  async function choose(id: string | null) {
    // Read the latest state first: other screens keep their own keys in the same file.
    const state: Record<string, any> = (await get('/api/ui-state').catch(() => ({}))) ?? {};
    const byWork = { ...(state.persona_by_work ?? {}) };
    if (id) byWork[workId] = id;
    else delete byWork[workId];
    const next = { ...state, persona_by_work: byWork };
    await put('/api/ui-state', next);
    qc.setQueryData(['ui-state'], next);
  }
  return { persona, selectedId, choose, list: list.data };
}

export default function PersonaDialog({
  list,
  selectedId,
  onChoose,
  onClose,
}: {
  list: PersonaList;
  selectedId: string | null;
  onChoose: (id: string | null) => Promise<void>;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  // The list being edited and the revision it came from are taken together when the dialog opens; a list refreshed
  // meanwhile (another window) must not lend its newer revision to this older copy.
  const [items, setItems] = useState<Persona[]>(list.personas);
  const [baseRevision] = useState(list.revision);
  const [focus, setFocus] = useState<string | null>(selectedId ?? list.personas[0]?.id ?? null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const current = items.find((p) => p.id === focus) ?? null;

  const edit = (patch: Partial<Persona>) => {
    setItems((all) => all.map((p) => (p.id === focus ? { ...p, ...patch } : p)));
    setDirty(true);
  };
  const add = (base?: Persona) => {
    // A temporary id; the server gives the real one when the list is saved.
    const id = `new-${Date.now().toString(36)}`;
    const name = base ? t('persona.copy_name', { name: base.name || t('persona.unnamed') }) : '';
    setItems((all) => [...all, { id, name, description: base?.description ?? '' }]);
    setFocus(id);
    setDirty(true);
  };
  const remove = () => {
    if (!current || !confirm(t('persona.delete_confirm', { name: current.name || t('persona.unnamed') }))) return;
    const rest = items.filter((p) => p.id !== current.id);
    setItems(rest);
    setFocus(rest[0]?.id ?? null);
    setDirty(true);
  };

  // Saves the list (when changed) and uses `use` for this work: a persona's position, or null for none.
  async function finish(use: number | null | 'keep') {
    setBusy(true);
    try {
      let saved = list;
      if (dirty) {
        saved = await put<PersonaList>('/api/personas', { base_revision: baseRevision, personas: items });
        qc.setQueryData(['personas'], saved);
      }
      // A saved list keeps the edited order (new ones get their ids there); an unchanged one is chosen by id.
      if (use !== 'keep') await onChoose(use === null ? null : dirty ? (saved.personas[use]?.id ?? null) : (items[use]?.id ?? null));
      else if (selectedId && !saved.personas.some((p) => p.id === selectedId)) await onChoose(null);
      onClose();
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  const close = () => {
    if (dirty && !confirm(t('persona.discard_confirm'))) return;
    onClose();
  };
  const position = current ? items.indexOf(current) : -1;

  return (
    <Dialog
      title={t('persona.title')}
      onClose={close}
      closeLabel={t('common.close')}
      className="wide"
      actions={
        <>
          <button disabled={busy} onClick={() => finish(null)}>
            {t('persona.use_none')}
          </button>
          {dirty && (
            <button disabled={busy} onClick={() => finish('keep')}>
              {t('persona.save_only')}
            </button>
          )}
          <button className="primary" disabled={busy || !current} onClick={() => finish(position)}>
            {t('persona.use')}
          </button>
        </>
      }
    >
      <p className="faint small">{t('persona.intro')}</p>
      <div className="persona-dialog">
        <div className="persona-list">
          {items.map((p) => (
            <button key={p.id} className={`list-row${p.id === focus ? ' on' : ''}`} onClick={() => setFocus(p.id)}>
              <span className="grow">{p.name || <span className="faint">{t('persona.unnamed')}</span>}</span>
              {p.id === selectedId && <span className="badge">{t('persona.in_use')}</span>}
            </button>
          ))}
          {items.length === 0 && <div className="faint small">{t('persona.empty')}</div>}
          <button onClick={() => add()}>+ {t('persona.add')}</button>
        </div>
        {current ? (
          <div className="col persona-form">
            <label>
              {t('persona.name')}
              <input value={current.name} maxLength={100} placeholder={t('persona.name_hint')} onChange={(e) => edit({ name: e.target.value })} autoFocus />
            </label>
            <label>
              {t('persona.description')}
              <textarea
                rows={12}
                value={current.description}
                placeholder={t('persona.description_hint')}
                onChange={(e) => edit({ description: e.target.value })}
              />
            </label>
            <div className="row">
              <span className="faint small grow">
                {t('persona.size', { chars: current.description.length.toLocaleString(), bytes: utf8(current.description).toLocaleString() })}
              </span>
              <button onClick={() => add(current)}>{t('jsx.duplicate')}</button>
              <button className="danger" onClick={remove}>
                {t('common.delete')}
              </button>
            </div>
          </div>
        ) : (
          <div className="empty">{t('persona.pick')}</div>
        )}
      </div>
    </Dialog>
  );
}
