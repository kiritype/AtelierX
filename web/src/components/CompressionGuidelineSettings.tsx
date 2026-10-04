import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiError, get, put } from '../api';
import { t, tm } from '../i18n';
import { useToast } from './Toasts';

type CompressionGuideline = { text: string; default_text: string; revision: string };

export default function CompressionGuidelineSettings({ onDirtyChange }: { onDirtyChange?: (dirty: boolean) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const guideline = useQuery<CompressionGuideline>({
    queryKey: ['compression-guideline'],
    queryFn: () => get('/api/settings/compression-guideline'),
  });
  const [draft, setDraft] = useState<string | null>(null);
  const [baseRevision, setBaseRevision] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const dirty = draft !== null && draft !== guideline.data?.text;
  const [stale, setStale] = useState(false);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  const beginDraft = (text: string) => {
    if (draft === null && guideline.data) setBaseRevision(guideline.data.revision);
    setDraft(text);
  };

  return (
    <div className="col" style={{ maxWidth: 760 }}>
      <h3>{t('settings.compression')}</h3>
      <p className="faint">{t('settings.compression_note')}</p>
      {guideline.isLoading && <p className="faint">{t('common.loading')}</p>}
      {guideline.isError && (
        <p role="alert" className="error">
          {guideline.error instanceof ApiError ? tm(guideline.error.msg) : String(guideline.error)}
        </p>
      )}
      {guideline.data && (
        <>
          <label className="col" style={{ gap: 4 }}>
            <span className="muted">{t('settings.compression_text')}</span>
            <textarea
              aria-label={t('settings.compression_text')}
              className="mono"
              rows={22}
              spellCheck={false}
              disabled={saving}
              value={draft ?? guideline.data.text}
              onChange={(event) => beginDraft(event.target.value)}
              style={{ width: '100%', resize: 'vertical', fontFamily: 'var(--mono, monospace)' }}
            />
          </label>
          <div className="row">
            <button disabled={saving} onClick={() => beginDraft(guideline.data!.default_text)}>
              {t('settings.compression_reset')}
            </button>
            <span className="grow" />
            <button
              disabled={saving || draft === null}
              onClick={async () => {
                if (stale) await guideline.refetch();
                setDraft(null);
                setBaseRevision(null);
                setStale(false);
              }}
            >
              {t('common.cancel')}
            </button>
            <button
              className="primary"
              disabled={saving || !dirty || baseRevision === null}
              onClick={async () => {
                if (draft === null || baseRevision === null) return;
                setSaving(true);
                try {
                  const saved = await put<CompressionGuideline>('/api/settings/compression-guideline', {
                    text: draft,
                    base_revision: baseRevision,
                  });
                  qc.setQueryData(['compression-guideline'], saved);
                  setDraft(null);
                  setBaseRevision(null);
                  toast({ text: t('common.saved') });
                } catch (error) {
                  if (error instanceof ApiError && error.status === 409) {
                    setStale(true);
                    qc.invalidateQueries({ queryKey: ['compression-guideline'] });
                  }
                  toast({
                    text: error instanceof ApiError ? tm(error.msg) : String(error),
                    tone: 'error',
                  });
                } finally {
                  setSaving(false);
                }
              }}
            >
              {saving ? t('common.saving') : t('common.save')}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
