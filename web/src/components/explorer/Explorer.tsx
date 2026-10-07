import { useMemo, useState, type ReactNode } from 'react';
import { t } from '../../i18n';

// A browsing screen for a set of things with pictures (style presets now, models later): search and facet filters on
// top, a card grid, a detail panel for the chosen one, and a side-by-side view of 2–4 checked ones. The screen that
// uses it says how an item looks; the explorer only arranges.
export type Facet<T> = { id: string; label: string; values: (item: T) => string[]; name?: (value: string) => string };

export default function Explorer<T>({
  items,
  idOf,
  search,
  facets,
  card,
  detail,
  compare,
  selected,
  onSelect,
  toolbar,
  empty,
  maxCompare = 4,
}: {
  items: T[];
  idOf: (item: T) => string;
  search: (item: T) => string;
  facets: Facet<T>[];
  card: (item: T) => ReactNode;
  detail: ReactNode;
  compare: (items: T[]) => ReactNode;
  selected: string | null;
  onSelect: (id: string) => void;
  // Actions on the right of the bar; a function gets the checked items (export the checked ones …).
  toolbar?: ReactNode | ((checked: T[]) => ReactNode);
  empty?: ReactNode;
  maxCompare?: number;
}) {
  const [query, setQuery] = useState('');
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [checked, setChecked] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);

  const options = useMemo(
    () => Object.fromEntries(facets.map((f) => [f.id, [...new Set(items.flatMap(f.values))].filter(Boolean).sort()])),
    [facets, items],
  );
  const shown = items.filter((item) => {
    if (query && !search(item).toLowerCase().includes(query.toLowerCase())) return false;
    return facets.every((f) => !chosen[f.id] || f.values(item).includes(chosen[f.id]));
  });
  const checkedItems = checked.map((id) => items.find((item) => idOf(item) === id)).filter((x): x is T => x !== undefined);
  const toggle = (id: string, on: boolean) =>
    setChecked(on ? [...checked.filter((x) => x !== id), id].slice(-maxCompare) : checked.filter((x) => x !== id));

  return (
    <div className="explorer">
      <div className="explorer-bar row">
        <input className="explorer-search" placeholder={t('explorer.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
        {facets.map((f) =>
          options[f.id].length > 0 ? (
            <select key={f.id} value={chosen[f.id] ?? ''} onChange={(e) => setChosen({ ...chosen, [f.id]: e.target.value })} aria-label={f.label}>
              <option value="">
                {f.label}: {t('explorer.all')}
              </option>
              {options[f.id].map((v) => (
                <option key={v} value={v}>
                  {f.name ? f.name(v) : v}
                </option>
              ))}
            </select>
          ) : null,
        )}
        <span className="faint small">{t('explorer.count', { n: shown.length, total: items.length })}</span>
        <span className="grow" />
        <button disabled={checkedItems.length < 2} className={comparing ? 'on' : ''} onClick={() => setComparing(!comparing)} title={t('explorer.compare_hint', { n: maxCompare })}>
          {t('explorer.compare', { n: checkedItems.length })}
        </button>
        {typeof toolbar === 'function' ? toolbar(checkedItems) : toolbar}
      </div>
      {comparing && checkedItems.length >= 2 ? (
        <div className="explorer-compare">
          <div className="row" style={{ marginBottom: 8 }}>
            <button className="ghost" onClick={() => setComparing(false)}>
              ← {t('explorer.back')}
            </button>
            <button className="ghost" onClick={() => (setChecked([]), setComparing(false))}>
              {t('explorer.clear')}
            </button>
          </div>
          {compare(checkedItems)}
        </div>
      ) : (
        <div className="explorer-body">
          <div className="explorer-grid">
            {shown.map((item) => {
              const id = idOf(item);
              return (
                <div key={id} className={`explorer-card${selected === id ? ' sel' : ''}`} onClick={() => onSelect(id)}>
                  <input
                    type="checkbox"
                    className="explorer-check"
                    checked={checked.includes(id)}
                    aria-label={t('explorer.check')}
                    title={t('explorer.compare_hint', { n: maxCompare })}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => toggle(id, e.target.checked)}
                  />
                  {card(item)}
                </div>
              );
            })}
            {shown.length === 0 && <div className="faint pad">{items.length ? t('explorer.none_match') : empty}</div>}
          </div>
          <aside className="explorer-detail">{detail}</aside>
        </div>
      )}
    </div>
  );
}
