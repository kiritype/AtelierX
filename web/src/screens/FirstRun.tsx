import { useState } from 'react';
import { ApiError, post } from '../api';
import { AppMark } from '../components/AppMark';
import { setLanguage, t, tm } from '../i18n';

export default function FirstRun({ onDone }: { onDone: () => void }) {
  const [language, setLang] = useState('ko');
  const [password, setPassword] = useState('');
  const [again, setAgain] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (password.length < 8) return setError(t('first_run.too_short'));
    if (password !== again) return setError(t('first_run.mismatch'));
    setBusy(true);
    try {
      await post('/api/auth/setup', { password, language });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? tm(err.msg) : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <form className="card" onSubmit={submit}>
        <h2>
          <AppMark size={28} />
        </h2>
        <p className="muted">{t('first_run.intro')}</p>
        <label>
          {t('first_run.language')}
          <select
            value={language}
            onChange={(e) => {
              setLang(e.target.value);
              setLanguage(e.target.value);
            }}
          >
            <option value="ko">한국어</option>
            <option value="en">English</option>
          </select>
        </label>
        <label>
          {t('first_run.password')}
          <input type="password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <label>
          {t('first_run.again')}
          <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} />
        </label>
        <p className="faint" style={{ margin: 0 }}>{t('first_run.note')}</p>
        {error && <div className="error-text">{error}</div>}
        <button className="primary" disabled={busy}>
          {t('first_run.start')}
        </button>
      </form>
    </div>
  );
}
