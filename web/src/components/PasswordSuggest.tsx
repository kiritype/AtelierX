import { useState } from 'react';
import { ApiError, post } from '../api';
import { t, tm } from '../i18n';
import { useToast } from './Toasts';
import { Dialog } from './ui';

// The master password used to unlock is shorter than new ones may be (#82): suggest a new one, or later.
export default function PasswordSuggest({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState({ old: '', new: '', again: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function save() {
    if (form.new.length < 8) return setError(t('first_run.too_short'));
    if (form.new !== form.again) return setError(t('first_run.mismatch'));
    setBusy(true);
    try {
      await post('/api/vault/password', { old: form.old, new: form.new });
      toast({ text: t('settings.password_changed') });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? tm(err.msg) : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={t('password_suggest.title')}
      onClose={onClose}
      closeLabel={t('password_suggest.later')}
      actions={
        <button className="primary" disabled={busy || !form.old || !form.new} onClick={save}>
          {t('password_suggest.change')}
        </button>
      }
    >
      <p className="muted">{t('password_suggest.body')}</p>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('settings.old_password')}</span>
        <input type="password" autoFocus value={form.old} onChange={(e) => setForm({ ...form, old: e.target.value })} />
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('settings.new_password')}</span>
        <input type="password" value={form.new} onChange={(e) => setForm({ ...form, new: e.target.value })} />
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('first_run.again')}</span>
        <input type="password" value={form.again} onChange={(e) => setForm({ ...form, again: e.target.value })} />
      </label>
      {error && <div className="error-text">{error}</div>}
    </Dialog>
  );
}
