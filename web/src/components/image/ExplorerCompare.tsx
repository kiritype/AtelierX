import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { msgText, t } from '../../i18n';
import type { ExplorerSession, ExplorerResult } from '../../styleExplorerTypes';
export default function ExplorerCompare({
  session: s,
  busy,
  active = true,
  vote,
}: {
  session: ExplorerSession;
  busy: boolean;
  active?: boolean;
  vote: (result: ExplorerResult) => void;
}) {
  const [revealed, setRevealed] = useState(false);
  const [failed, setFailed] = useState<string[]>([]);
  const comparator = useRef<HTMLElement>(null);
  const pair = s.pair;
  useEffect(() => {
    setRevealed(false);
    setFailed([]);
  }, [pair?.id]);
  const a = s.candidates.find((c) => c.id === pair?.a),
    b = s.candidates.find((c) => c.id === pair?.b);
  const valid = !!a?.image_url && !!b?.image_url && ![a.id, b.id].some((id) => failed.includes(id));
  const choose = (result: ExplorerResult) => {
    comparator.current?.focus({ preventScroll: true });
    vote(result);
    setRevealed(false);
  };
  const keydown = (e: KeyboardEvent) => {
    if (
      !active ||
      e.defaultPrevented ||
      e.repeat ||
      e.nativeEvent.isComposing ||
      (e.target as HTMLElement).closest('input,textarea,select,[contenteditable]:not([contenteditable="false"])') ||
      document.querySelector('[aria-modal="true"]') ||
      e.ctrlKey ||
      e.altKey ||
      e.metaKey ||
      e.shiftKey
    )
      return;
    const result = (
      {
        a: 'a',
        b: 'b',
        '1': 'a',
        '2': 'b',
        '3': 'tie',
        '4': 'neither',
        '5': 'skip',
        t: 'tie',
        n: 'neither',
        s: 'skip',
      } as Record<string, ExplorerResult>
    )[e.key.toLowerCase()];
    if (result && valid && !busy) {
      e.preventDefault();
      choose(result);
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
  return (
    <section
      ref={comparator}
      className="col explorer-comparator"
      tabIndex={0}
      onKeyDown={keydown}
      aria-label={t('style_explorer.compare')}
    >
      {!pair || !a || !b ? (
        <p className="faint">{t(complete ? 'style_explorer.completed' : 'style_explorer.wait_pair')}</p>
      ) : (
        <>
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
                  disabled={busy || !valid || !active}
                  aria-keyshortcuts={`${i + 1} ${i === 0 ? 'A' : 'B'}`}
                  onClick={() => choose(i === 0 ? 'a' : 'b')}
                >
                  <kbd aria-hidden="true">{i + 1}</kbd> {t(i === 0 ? 'style_explorer.prefer_a' : 'style_explorer.prefer_b')}
                </button>
              </div>
            ))}
          </div>
          <div className="row">
            {(['tie', 'neither', 'skip'] as const).map((result, i) => (
              <button
                key={result}
                disabled={busy || !valid || !active}
                aria-keyshortcuts={`${i + 3} ${['T', 'N', 'S'][i]}`}
                onClick={() => choose(result)}
              >
                <kbd aria-hidden="true">{i + 3}</kbd> {t(`style_explorer.${result}`)}
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
        </>
      )}
    </section>
  );
}
