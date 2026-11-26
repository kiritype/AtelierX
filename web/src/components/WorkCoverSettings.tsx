import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { ApiError, get, notifyUnauthorized, post, put, type ServerMessage } from '../api';
import { t, tm } from '../i18n';
import type { WorkCovers } from '../types';
import { useToast } from './Toasts';
import { useUnsaved } from './Unsaved';
import { Dialog } from './ui';
import type { GalleryItem } from './image/ImageGallery';

const errorText = (error: unknown) => error instanceof ApiError ? tm(error.msg) : String(error);

async function uploadCover(endpoint: string, file: File, revision: string): Promise<WorkCovers> {
  const params = new URLSearchParams({ filename: file.name, base_revision: revision });
  const response = await fetch(endpoint + '/upload?' + params, {
    method: 'POST',
    body: file,
    credentials: 'same-origin',
  });
  const data = await response.json().catch(() => null) as WorkCovers | { error: ServerMessage } | null;
  if (response.status === 401) notifyUnauthorized();
  if (!response.ok || !data || !('items' in data)) {
    throw new ApiError(response.status, data && 'error' in data ? data.error : {
      key: 'work_covers.upload_failed',
      text: 'Could not upload the cover.',
    });
  }
  return data;
}

export default function WorkCoverSettings({ workId }: { workId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const endpoint = '/api/works/' + encodeURIComponent(workId) + '/covers';
  const queryKey = ['work-covers', workId];
  const covers = useQuery({ queryKey, queryFn: () => get<WorkCovers>(endpoint) });
  const [picking, setPicking] = useState(false);
  const mutation = useMutation({
    mutationFn: (request: () => Promise<WorkCovers>) => request(),
    onMutate: () => qc.cancelQueries({ queryKey, exact: true }),
    onSuccess: (saved) => {
      qc.setQueryData(queryKey, saved);
      void qc.invalidateQueries({ queryKey: ['works'] });
      toast({ text: t('common.saved') });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.msg.key === 'server.save.stale') {
        void qc.invalidateQueries({ queryKey, exact: true });
      }
      toast({ text: errorText(error), tone: 'error' });
    },
  });
  useUnsaved('work-covers', mutation.isPending);

  const data = covers.data;
  const busy = !data || covers.isFetching || mutation.isPending;
  function saveOrder(ids: string[], primaryId: string | null) {
    if (!data || busy) return;
    mutation.mutate(() => put<WorkCovers>(endpoint, { ids, primary_id: primaryId, base_revision: data.revision }));
  }

  return (
    <section className="col work-covers" aria-label={t('work_covers.title')}>
      <div className="section-title">{t('work_covers.title')}</div>
      <div className="row wrap">
        <input ref={input} type="file" accept="image/png,image/webp,image/jpeg" hidden onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = '';
          if (file && data && !busy) mutation.mutate(() => uploadCover(endpoint, file, data.revision));
        }} />
        <button type="button" disabled={busy} onClick={() => input.current?.click()}>{t('work_covers.add_file')}</button>
        <button type="button" disabled={busy} onClick={() => setPicking(true)}>{t('work_covers.add_gallery')}</button>
        {mutation.isPending && <span className="faint" role="status">{t('common.saving')}</span>}
      </div>
      {covers.isError ? (
        <div className="row wrap">
          <span className="error-text">{errorText(covers.error)}</span>
          <button type="button" onClick={() => void covers.refetch()}>{t('common.retry')}</button>
        </div>
      ) : !data ? (
        <p className="faint" role="status">{t('common.loading')}</p>
      ) : data.items.length === 0 ? (
        <p className="faint">{t('work_covers.empty')}</p>
      ) : (
        <div className="col">
          {data.items.map((item, index) => {
            const primary = item.id === data.primary_id;
            const move = (direction: number) => {
              const ids = data.items.map(cover => cover.id);
              const next = index + direction;
              [ids[index], ids[next]] = [ids[next], ids[index]];
              saveOrder(ids, data.primary_id);
            };
            const remove = () => {
              const ids = data.items.filter(cover => cover.id !== item.id).map(cover => cover.id);
              saveOrder(ids, primary ? ids[0] ?? null : data.primary_id);
            };
            return (
              <div className="row wrap work-cover-row" key={item.id}>
                <img className="work-cover-thumb" src={item.url} alt="" loading="lazy" />
                <span className="grow">{item.name}</span>
                {primary ? <span className="chip accent">{t('work_covers.primary')}</span> : (
                  <button type="button" disabled={busy} onClick={() => saveOrder(data.items.map(cover => cover.id), item.id)}>
                    {t('work_covers.make_primary')}
                  </button>
                )}
                <div className="row">
                  <button type="button" disabled={busy || index === 0} title={t('work_covers.move_up')}
                    aria-label={t('work_covers.move_up_name', { name: item.name })} onClick={() => move(-1)}>↑</button>
                  <button type="button" disabled={busy || index === data.items.length - 1} title={t('work_covers.move_down')}
                    aria-label={t('work_covers.move_down_name', { name: item.name })} onClick={() => move(1)}>↓</button>
                  <button type="button" disabled={busy} aria-label={t('work_covers.remove_name', { name: item.name })}
                    onClick={remove}>{t('common.delete')}</button>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {picking && <CoverGallery workId={workId} busy={busy}
        onClose={() => setPicking(false)} onPick={(path) => {
          if (!data || busy) return;
          mutation.mutate(() => post<WorkCovers>(endpoint, { gallery_path: path, base_revision: data.revision }), {
            onSuccess: () => setPicking(false),
          });
        }} />}
    </section>
  );
}

type GalleryPage = { results: Pick<GalleryItem, 'path' | 'filename' | 'thumbnail_url'>[]; pages: number };

function CoverGallery({ workId, busy, onClose, onPick }: {
  workId: string;
  busy: boolean;
  onClose: () => void;
  onPick: (path: string) => void;
}) {
  const [page, setPage] = useState(1);
  const params = new URLSearchParams({ library_work: workId, work: workId, page: String(page), page_size: '24' });
  const gallery = useQuery({
    queryKey: ['work-cover-gallery', workId, page],
    queryFn: () => get<GalleryPage>('/api/image/gallery?' + params),
    staleTime: 0,
  });
  const results = (gallery.data?.results ?? []).filter(({ path }) => {
    const parts = path.split('/');
    return (parts.length === 6 && parts[0] === workId && parts[2] === 'images') ||
      (parts.length === 4 && parts[0] === '_single' && parts[1] === workId);
  });
  const pages = gallery.data?.pages ?? 0;

  return (
    <Dialog title={t('work_covers.add_gallery')} onClose={onClose} closeLabel={t('common.close')} className="work-cover-gallery-dialog">
      {gallery.isError ? (
        <div className="row wrap">
          <span className="error-text">{errorText(gallery.error)}</span>
          <button type="button" onClick={() => void gallery.refetch()}>{t('common.retry')}</button>
        </div>
      ) : gallery.isPending ? (
        <p className="faint" role="status">{t('common.loading')}</p>
      ) : results.length === 0 ? (
        <p className="faint">{t('work_covers.gallery_empty')}</p>
      ) : (
        <div className="work-cover-gallery">
          {results.map(image => (
            <button type="button" key={image.path} disabled={busy} title={image.path} onClick={() => onPick(image.path)}>
              <img src={image.thumbnail_url} alt="" loading="lazy" />
              <span>{image.filename}</span>
            </button>
          ))}
        </div>
      )}
      {(page > 1 || pages > 1) && (
        <div className="row work-cover-pages">
          <button type="button" disabled={busy || page <= 1} onClick={() => setPage(page - 1)}>{t('work_covers.previous_page')}</button>
          <span>{page} / {Math.max(page, pages)}</span>
          <button type="button" disabled={busy || page >= pages} onClick={() => setPage(page + 1)}>{t('work_covers.next_page')}</button>
        </div>
      )}
      {busy && <span className="faint" role="status">{t('common.saving')}</span>}
    </Dialog>
  );
}
