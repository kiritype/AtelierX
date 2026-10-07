import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get, put } from '../../api';
import { t, tm } from '../../i18n';

// Image menu → Models → Search (#161): Civitai models by words, kind, base model and order. Adult models and adult
// preview images stay out unless "Include NSFW" is on (off by default; the last choice is kept in the image settings).
type Found = {
  id: number;
  name: string;
  type: string;
  nsfw: boolean;
  creator: string;
  base_model: string;
  version: string;
  image: string | null;
  image_is_video: boolean;
  downloads: number;
  likes: number;
  url: string;
};
const KINDS = ['', 'Checkpoint', 'LORA', 'LoCon', 'DoRA', 'TextualInversion', 'VAE', 'Upscaler'];
const BASES = ['', 'Anima', 'Illustrious', 'NoobAI', 'Pony', 'SDXL 1.0', 'Krea 2'];
const SORTS = ['Highest Rated', 'Most Downloaded', 'Newest'];
const count = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));

export default function ModelSearch({ onPick }: { onPick: (address: string) => void }) {
  const qc = useQueryClient();
  const settings = useQuery<{ nsfw: boolean }>({ queryKey: ['image-settings', 'downloads'], queryFn: () => get('/api/image/settings/downloads') });
  const [draft, setDraft] = useState('');
  const [form, setForm] = useState({ query: '', kind: 'LORA', base: 'Anima', sort: 'Highest Rated' });
  const nsfw = settings.data?.nsfw ?? false;
  const params = (cursor?: string) =>
    new URLSearchParams({ ...form, nsfw: String(nsfw), ...(cursor ? { cursor } : {}) }).toString();
  const results = useInfiniteQuery<{ items: Found[]; next: string | null }>({
    queryKey: ['civitai-search', form, nsfw],
    queryFn: ({ pageParam }) => get(`/api/image/models/search?${params(pageParam as string | undefined)}`),
    initialPageParam: undefined,
    getNextPageParam: (last) => last.next ?? undefined,
    enabled: !!settings.data,
    retry: false,
    staleTime: 5 * 60_000,
  });
  const items = (results.data?.pages ?? []).flatMap((p) => p.items);
  const pick = (field: keyof typeof form, options: string[], label: string) => (
    <select value={form[field]} onChange={(e) => setForm({ ...form, [field]: e.target.value })} aria-label={label}>
      {options.map((o) => (
        <option key={o} value={o}>
          {o ? (field === 'sort' ? t(`models.search.sort.${o}`) : o) : `${label}: ${t('explorer.all')}`}
        </option>
      ))}
    </select>
  );

  return (
    <div className="explorer">
      <div className="explorer-bar row">
        <input
          className="explorer-search"
          placeholder={t('models.search.query')}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && setForm({ ...form, query: draft.trim() })}
        />
        <button onClick={() => setForm({ ...form, query: draft.trim() })}>{t('models.search.go')}</button>
        {pick('kind', KINDS, t('models.facet.kind'))}
        {pick('base', BASES, t('models.facet.base'))}
        {pick('sort', SORTS, t('models.search.sort_label'))}
        <label className="row small" style={{ gap: 4 }} title={t('models.search.nsfw_hint')}>
          <input
            type="checkbox"
            checked={nsfw}
            onChange={async (e) => {
              await put('/api/image/settings/downloads', { nsfw: e.target.checked });
              qc.invalidateQueries({ queryKey: ['image-settings', 'downloads'] });
            }}
          />
          {t('models.search.nsfw')}
        </label>
      </div>
      {results.isError && <div className="pad warn-text">{results.error instanceof ApiError ? tm(results.error.msg) : String(results.error)}</div>}
      <div className="explorer-grid" style={{ flex: 1 }}>
        {items.map((m) => (
          <div key={m.id} className="explorer-card" onClick={() => onPick(m.url)} title={t('models.search.pick_hint')}>
            <div className="preset-thumb">
              {m.image && !m.image_is_video ? (
                <img src={m.image} alt="" loading="lazy" referrerPolicy="no-referrer" />
              ) : (
                <span className="faint small">{m.type}</span>
              )}
            </div>
            <div className="col" style={{ gap: 2, padding: '6px 8px' }}>
              <strong className="ellipsis" title={m.name}>
                {m.name}
              </strong>
              <span className="faint small ellipsis">
                {m.creator} · {m.version}
              </span>
              <div className="row" style={{ gap: 4, flexWrap: 'wrap' }}>
                <span className="chip small">{m.type}</span>
                {m.base_model && <span className="chip small">{m.base_model}</span>}
                {m.nsfw && <span className="chip small warn">NSFW</span>}
                <span className="faint small">
                  ↓{count(m.downloads)} · ♥{count(m.likes)}
                </span>
              </div>
            </div>
          </div>
        ))}
        {!results.isLoading && items.length === 0 && !results.isError && <div className="faint pad">{t('models.search.none')}</div>}
        {results.isLoading && <div className="faint pad">{t('models.search.loading')}</div>}
      </div>
      {results.hasNextPage && (
        <div className="row pad">
          <button disabled={results.isFetchingNextPage} onClick={() => results.fetchNextPage()}>
            {t('models.search.more')}
          </button>
        </div>
      )}
    </div>
  );
}
