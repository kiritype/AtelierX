import { useMemo, useState } from 'react';
import { t } from '../../i18n';
import { columnState, outfitColumns, rowState, selectionState, allOutfits, setColumn, setOutfit, setRow, type Selection } from '../../lib/outfitColumns';

// Generate screen (#208): characters as rows, outfits lined up by deployment code (then by name) as columns. A row head
// selects all of that character's outfits, a column head that outfit of every character, the corner everything.
type Character = { id: string; name: string; path: string; has_design: boolean; outfits: { id: string; name: string; code?: string }[] };

function Box({ state, onChange, label, disabled }: { state: 'all' | 'some' | 'none'; onChange: (on: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <input
      type="checkbox"
      aria-label={label}
      disabled={disabled}
      checked={state === 'all'}
      ref={(el) => {
        if (el) el.indeterminate = state === 'some';
      }}
      onChange={() => onChange(state !== 'all')}
    />
  );
}

export default function CharacterOutfitTable({ characters, value, onChange, openItem }: { characters: Character[]; value: Selection; onChange: (next: Selection) => void; openItem: (path: string) => void }) {
  const [filter, setFilter] = useState('');
  const [onlyChosen, setOnlyChosen] = useState(false);
  const [folded, setFolded] = useState(false);
  const { columns, others } = useMemo(() => outfitColumns(characters), [characters]);
  const hasOthers = Object.keys(others).length > 0;
  const chosenChars = Object.keys(value).length;
  const chosenOutfits = Object.values(value).reduce((n, list) => n + list.length, 0);
  const shown = characters.filter(
    (c) => (!filter || `${c.id} ${c.name}`.toLowerCase().includes(filter.toLowerCase())) && (!onlyChosen || value[c.id]?.length),
  );
  const usable = characters.filter((c) => c.has_design);

  return (
    <div className="col gen-table-wrap">
      <div className="row" style={{ gap: 8 }}>
        <div className="section-title grow" style={{ margin: 0 }}>
          {t('gen.characters')} <span className="faint small">{t('gen.table.summary', { chars: chosenChars, outfits: chosenOutfits })}</span>
        </div>
        {!folded && (
          <>
            <input placeholder={t('gen.table.find')} value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 160 }} />
            <label className="row small" style={{ gap: 4 }}>
              <input type="checkbox" checked={onlyChosen} onChange={(e) => setOnlyChosen(e.target.checked)} />
              {t('gen.table.only_chosen')}
            </label>
          </>
        )}
        <button className="small" onClick={() => setFolded(!folded)}>
          {folded ? t('gen.table.unfold') : t('gen.table.fold')}
        </button>
      </div>
      {characters.length === 0 && <div className="faint">{t('gen.no_characters')}</div>}
      {!folded && characters.length > 0 && (
        <div className="gen-table-scroll">
          <table className="gen-table">
            <thead>
              <tr>
                <th className="gen-table-row-head">
                  <label className="row" style={{ gap: 4 }}>
                    <Box state={selectionState(value, usable)} onChange={(on) => onChange(on ? allOutfits(usable) : {})} label={t('gen.table.all')} disabled={!usable.length} />
                    {t('gen.table.all')} <span className="faint">({usable.length})</span>
                  </label>
                </th>
                {columns.map((column) => (
                  <th key={column.key}>
                    <label className="row" style={{ gap: 4 }} title={t('gen.table.column_hint')}>
                      <Box state={columnState(value, column)} onChange={(on) => onChange(setColumn(value, column, on))} label={column.name} />
                      {column.code && <span className="mono">{column.code}</span>} {column.name} <span className="faint">({Object.keys(column.members).length})</span>
                    </label>
                  </th>
                ))}
                {hasOthers && <th className="faint">{t('gen.table.others')}</th>}
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => (
                <tr key={c.id} className={value[c.id]?.length ? 'on' : undefined}>
                  <th className="gen-table-row-head">
                    {c.has_design ? (
                      <label className="row" style={{ gap: 4 }} title={t('gen.table.row_hint')}>
                        <Box state={rowState(value, c)} onChange={(on) => onChange(setRow(value, c, on))} label={c.name} />
                        <strong>{c.name}</strong> <span className="faint mono">{c.id}</span>
                      </label>
                    ) : (
                      <span className="row" style={{ gap: 4 }}>
                        <span className="faint">{c.name}</span>
                        <a href="#" onClick={(e) => (e.preventDefault(), openItem(c.path))} className="faint small">
                          {t('gen.no_design')}
                        </a>
                      </span>
                    )}
                  </th>
                  {columns.map((column) => {
                    const oid = column.members[c.id];
                    return (
                      <td key={column.key}>
                        {oid && (
                          <input
                            type="checkbox"
                            aria-label={`${c.name} ${column.name}`}
                            checked={!!value[c.id]?.includes(oid)}
                            onChange={(e) => onChange(setOutfit(value, c.id, oid, e.target.checked))}
                          />
                        )}
                      </td>
                    );
                  })}
                  {hasOthers && (
                    <td className="gen-table-others">
                      {(others[c.id] ?? []).map((o) => (
                        <label key={o.id} className="row small" style={{ gap: 4, display: 'inline-flex', marginRight: 8 }}>
                          <input type="checkbox" checked={!!value[c.id]?.includes(o.id)} onChange={(e) => onChange(setOutfit(value, c.id, o.id, e.target.checked))} />
                          {o.name}
                        </label>
                      ))}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
