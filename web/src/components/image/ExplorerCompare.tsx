import { useState, type KeyboardEvent } from 'react';
import { msgText, t } from '../../i18n';
import type { ExplorerSession, ExplorerResult } from '../../styleExplorerTypes';
export default function ExplorerCompare({
  session: s,
  busy,
  vote,
}: {
  session: ExplorerSession;
  busy: boolean;
  vote: (result: ExplorerResult) => void;
}) {
  const [revealed, setRevealed] = useState(false);
  const [failed, setFailed] = useState<string[]>([]);
  const pair = s.pair;
  const a = s.candidates.find((c) => c.id === pair?.a),
    b = s.candidates.find((c) => c.id === pair?.b);
  const valid = !!a?.image_url && !!b?.image_url && ![a.id, b.id].some((id) => failed.includes(id));
  const keydown = (e: KeyboardEvent) => {
    if (
      (e.target as HTMLElement).closest('input,textarea,select,[contenteditable="true"]') ||
      e.ctrlKey ||
      e.altKey ||
      e.metaKey
    )
      return;
    const result = (
      {
        a: 'a',
        b: 'b',
        '1': 'a',
        '2': 'b',
        t: 'tie',
        n: 'neither',
        s: 'skip',
      } as Record<string, ExplorerResult>
    )[e.key.toLowerCase()];
    if (result && valid && !busy) {
      e.preventDefault();
      vote(result);
      setRevealed(false);
    }
  };
  const ready = s.candidates.filter((c) => c.status === 'done' && c.image_url);
  const complete =
    ready.length >= 2 &&
    ready.every((left, i) =>
      ready
        .slice(i + 1)
        .every((right) =>
          s.votes.some((v) => (v.a === left.id && v.b === right.id) || (v.b === left.id && v.a === right.id)),
        ),
    );
  if (!pair || !a || !b)
    return <p className="faint">{t(complete ? 'style_explorer.completed' : 'style_explorer.wait_pair')}</p>;
  return (
    <section
      key={pair.id}
      className="col explorer-comparator"
      tabIndex={0}
      onKeyDown={keydown}
      aria-label={t('style_explorer.compare')}
    >
      <p>{t('style_explorer.blind_about')}</p>
      <div className="explorer-pair">
        {[a, b].map((candidate, i) => (
          <div className="col" key={candidate.id}>
            {candidate.image_url && !failed.includes(candidate.id) ? (
              <img
                src={candidate.image_url}
                alt={i === 0 ? 'A' : 'B'}
                onError={() => setFailed((ids) => [...ids, candidate.id])}
              />
            ) : (
              <p role="alert">{t('style_explorer.missing_image')}</p>
            )}
            <button
              className="primary explorer-choice"
              disabled={busy || !valid}
              onClick={() => {
                vote(i === 0 ? 'a' : 'b');
                setRevealed(false);
              }}
            >
              {i === 0 ? 'A' : 'B'} · {t('style_explorer.choose')}
            </button>
          </div>
        ))}
      </div>
      <div className="row">
        {(['tie', 'neither', 'skip'] as const).map((result) => (
          <button
            key={result}
            disabled={busy || !valid}
            onClick={() => {
              vote(result);
              setRevealed(false);
            }}
          >
            {t(`style_explorer.${result}`)}
          </button>
        ))}
        <button className="ghost" onClick={() => setRevealed(!revealed)} aria-expanded={revealed}>
          {t('style_explorer.reveal')}
        </button>
      </div>
      {revealed && (
        <div className="explorer-pair">
          {[a, b].map((candidate) => (
            <div key={candidate.id}>
              <p>
                {t('style_explorer.seed')}: {candidate.seed}
              </p>
              <pre>
                {JSON.stringify(
                  {
                    positive: candidate.positive,
                    negative: candidate.negative,
                    settings: candidate.settings,
                    artists: candidate.artists,
                  },
                  null,
                  2,
                )}
              </pre>
              {!!candidate.error && <p>{msgText(candidate.error)}</p>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
