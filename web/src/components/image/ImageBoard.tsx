import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Fragment, useState } from 'react';
import { ApiError, get, put } from '../../api';
import { t, tm } from '../../i18n';
import { useToast } from '../Toasts';
import { sendToGenerate, type Target } from './ImageGenerate';

// Character image completeness board (#45): outfits × expressions per character, what each combination still needs.
type Cell = { state: 'missing' | 'generated' | 'adopted' | 'excluded'; images: number; queued: number };
type Character = { id: string; name: string; outfits: { id: string; name: string }[]; cells: Record<string, Cell>; required: number; adopted: number };
type Board = { expressions: { id: string; name: string; rating: string }[]; characters: Character[]; required: number; adopted: number };

const MARK: Record<Cell['state'], string> = { adopted: '✓', generated: '', missing: '', excluded: '–' };

export default function ImageBoard({
  workId,
  openGenerate,
  openGallery,
}: {
  workId: string;
  openGenerate: () => void;
  openGallery: (characterId: string, outfitId: string) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const board = useQuery<Board>({ queryKey: ['image-board', workId], queryFn: () => get(`/api/works/${workId}/image/board`), refetchInterval: 5000 });
  const [editing, setEditing] = useState<string | null>(null);

  async function exclude(characterId: string, combos: string[], excluded: boolean) {
    try {
      qc.setQueryData(['image-board', workId], await put(`/api/works/${workId}/image/board/exclude`, { character_id: characterId, combos, excluded }));
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  // Hand the chosen combinations to the generate screen, where the model and preset are picked and the count is shown.
  function generate(character: Character, withUnadopted: boolean) {
    const targets: Target[] = Object.entries(character.cells)
      .filter(([, cell]) => !cell.queued && (cell.state === 'missing' || (withUnadopted && cell.state === 'generated')))
      .map(([combo]) => {
        const [outfit_id, expression_id] = combo.split('/');
        return { character_id: character.id, outfit_id, expression_id };
      });
    if (!targets.length) return;
    sendToGenerate(targets);
    openGenerate();
  }

  if (!board.data) return <div className="pad faint">…</div>;
  const { expressions, characters } = board.data;
  const percent = (a: number, r: number) => (r ? Math.round((a / r) * 100) : 100);

  return (
    <div className="pad col image-board">
      <div className="row wrap">
        <h3 className="grow" style={{ margin: 0 }}>{t('board.title')}</h3>
        <span className="nowrap">{t('board.progress', { adopted: board.data.adopted, required: board.data.required, percent: percent(board.data.adopted, board.data.required) })}</span>
      </div>
      <p className="faint small">{t('board.about')}</p>
      <div className="row wrap small board-legend">
        <span className="board-cell state-adopted">✓</span> {t('board.state.adopted')}
        <span className="board-cell state-generated">2</span> {t('board.state.generated')}
        <span className="board-cell state-missing" /> {t('board.state.missing')}
        <span className="board-cell state-excluded">–</span> {t('board.state.excluded')}
        <span className="board-cell state-missing queued" /> {t('board.state.queued')}
      </div>
      {characters.length === 0 && <div className="empty">{t('board.no_characters')}</div>}
      {characters.map((character) => {
        const missing = Object.values(character.cells).filter((c) => c.state === 'missing' && !c.queued).length;
        const unadopted = Object.values(character.cells).filter((c) => c.state === 'generated' && !c.queued).length;
        const edit = editing === character.id;
        const combos = (pick: (outfit: string, expression: string) => boolean) =>
          character.outfits.flatMap((o) => expressions.filter((e) => pick(o.id, e.id)).map((e) => `${o.id}/${e.id}`));
        // A whole row or column goes in or out together: out unless all of it is out already.
        const toggleAll = (list: string[]) => exclude(character.id, list, !list.every((c) => character.cells[c]?.state === 'excluded'));
        return (
          <section key={character.id} className="col board-character">
            <div className="row wrap">
              <strong className="nowrap">{character.name}</strong>
              <span className="faint mono">{character.id}</span>
              <span className="grow faint nowrap">{t('board.progress', { adopted: character.adopted, required: character.required, percent: percent(character.adopted, character.required) })}</span>
            </div>
            <div className="row wrap">
              <button disabled={!missing} onClick={() => generate(character, false)}>{t('board.generate_missing', { n: missing })}</button>
              <button disabled={!missing && !unadopted} onClick={() => generate(character, true)}>{t('board.generate_unadopted', { n: missing + unadopted })}</button>
              <button className={edit ? 'primary' : ''} onClick={() => setEditing(edit ? null : character.id)}>{edit ? t('board.edit_done') : t('board.edit_exclusions')}</button>
            </div>
            {edit && <p className="faint small">{t('board.edit_help')}</p>}
            <div className="board-grid" style={{ gridTemplateColumns: `minmax(90px, max-content) repeat(${expressions.length}, minmax(34px, 1fr))` }}>
              <span />
              {expressions.map((e) => (
                <button key={e.id} className="board-head ghost" disabled={!edit} title={e.id} onClick={() => toggleAll(combos((_, x) => x === e.id))}>
                  {e.name}
                </button>
              ))}
              {character.outfits.map((outfit) => (
                <Fragment key={outfit.id}>
                  <button className="board-head ghost row-head" disabled={!edit} title={outfit.id} onClick={() => toggleAll(combos((o) => o === outfit.id))}>
                    {outfit.name}
                  </button>
                  {expressions.map((e) => {
                    const combo = `${outfit.id}/${e.id}`;
                    const cell = character.cells[combo] ?? { state: 'missing', images: 0, queued: 0 };
                    const title = [`${outfit.name} · ${e.name}`, t(`board.state.${cell.state}`), cell.images ? t('board.images', { n: cell.images }) : '', cell.queued ? t('board.queued', { n: cell.queued }) : '']
                      .filter(Boolean)
                      .join(' · ');
                    return (
                      <button
                        key={combo}
                        className={`board-cell state-${cell.state}${cell.queued ? ' queued' : ''}`}
                        title={title}
                        aria-label={title}
                        disabled={!edit && !cell.images}
                        onClick={() => (edit ? exclude(character.id, [combo], cell.state !== 'excluded') : openGallery(character.id, outfit.id))}
                      >
                        {cell.state === 'generated' ? cell.images : MARK[cell.state]}
                      </button>
                    );
                  })}
                </Fragment>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
