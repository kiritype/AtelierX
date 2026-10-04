import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get, post } from '../api';
import { t, tm } from '../i18n';
import RunLlmSelector, { type LlmOverride } from './RunLlmSelector';
import { useToast } from './Toasts';
import { Dialog } from './ui';

// 04-authoring: 뼈대 작성 — answer the scale's questions; the result arrives as a draft to review.
export default function AuthoringDialog({ workId, onClose }: { workId: string; onClose: () => void }) {
  const toast = useToast();
  const [scale, setScale] = useState<string | null>(null);
  const questions = useQuery<{ scale: string; guideline: string; questions: string[] }>({
    queryKey: ['authoring-questions', workId, scale],
    queryFn: () => get(`/api/works/${workId}/authoring/questions${scale ? `?scale=${scale}` : ''}`),
  });
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [free, setFree] = useState('');
  const [llm, setLlm] = useState<LlmOverride | undefined>();
  const list = questions.data?.questions ?? [];

  async function run() {
    const payload = list.length
      ? list.map((question, n) => ({ question, answer: answers[n] ?? '' }))
      : [{ question: t('authoring.free_question'), answer: free }];
    try {
      await post(`/api/works/${workId}/authoring`, { scale: questions.data?.scale, answers: payload, llm });
      toast({ text: t('authoring.started') });
      onClose();
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  return (
    <Dialog
      title={t('authoring.title')}
      onClose={onClose}
      actions={
        <button className="primary" onClick={run} disabled={!questions.data}>
          {t('authoring.run')}
        </button>
      }
    >
      <div className="row">
        <span className="muted">{t('works.scale')}</span>
        <select value={questions.data?.scale ?? ''} onChange={(e) => (setScale(e.target.value), setAnswers({}))}>
          {['single', 'ensemble', 'simulation'].map((s) => (
            <option key={s} value={s}>
              {t(`scale.${s}`)}
            </option>
          ))}
        </select>
        <span className="faint grow">{questions.data && t('authoring.from', { name: questions.data.guideline })}</span>
      </div>
      <p className="faint">{t('authoring.note')}</p>
      <RunLlmSelector task="authoring" value={llm} onChange={setLlm} disabled={!questions.data} />
      <div className="col" style={{ maxHeight: '55vh', overflow: 'auto', gap: 10 }}>
        {list.map((question, n) => (
          <label key={n} className="col" style={{ gap: 2 }}>
            <span>
              {n + 1}. {question}
            </span>
            <textarea rows={2} value={answers[n] ?? ''} onChange={(e) => setAnswers({ ...answers, [n]: e.target.value })} />
          </label>
        ))}
        {questions.data && list.length === 0 && (
          <label className="col" style={{ gap: 2 }}>
            <span>{t('authoring.free_question')}</span>
            <textarea rows={6} value={free} onChange={(e) => setFree(e.target.value)} />
          </label>
        )}
      </div>
    </Dialog>
  );
}
