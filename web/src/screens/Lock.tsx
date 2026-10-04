import { useState } from 'react';
import { ApiError, post } from '../api';
import { t, tm } from '../i18n';

export default function Lock({ wait, onDone }: { wait: number; onDone: () => void }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState(wait ? t('lock.wait', { n: wait }) : '');
  const [forgot, setForgot] = useState(false);
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);

  async function unlock(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await post('/api/auth/unlock', { password });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? tm(err.msg) : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function reset(event: React.FormEvent) {
    event.preventDefault();
    try {
      await post('/api/auth/reset', { password, confirm });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? tm(err.msg) : String(err));
    }
  }

  if (forgot) {
    return (
      <div className="center">
        <form className="card" onSubmit={reset}>
          <h2>{t('lock.reset_title')}</h2>
          <p className="muted">{t('lock.reset_note')}</p>
          <label>
            {t('lock.new_password')}
            <input type="password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <label>
            {t('lock.type_reset')}
            <input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="RESET" />
          </label>
          {error && <div className="error-text">{error}</div>}
          <div className="row">
            <button type="button" onClick={() => setForgot(false)}>
              {t('common.back')}
            </button>
            <span className="grow" />
            <button className="primary danger">{t('lock.reset')}</button>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="center">
      <form className="card" onSubmit={unlock}>
        <h2>AtelierX</h2>
        <label>
          {t('lock.password')}
          <input type="password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <div className="error-text">{error}</div>}
        <div className="row">
          <button type="button" className="ghost" onClick={() => setForgot(true)}>
            {t('lock.forgot')}
          </button>
          <span className="grow" />
          <button className="primary" disabled={busy}>
            {t('lock.open')}
          </button>
        </div>
      </form>
    </div>
  );
}
