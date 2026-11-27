import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, get, put } from '../../api';
import type { AnimaReferenceEngine, ReferenceAsset, ReferenceDraftFile, SnapRefMode } from '../../imageTypes';
import { t, tm } from '../../i18n';
import { FAMILY_DEFAULTS, type GenerationSettings } from './GenSettings';

export type ReferenceFamily = 'anima' | 'moss';
type FamilyDraft = { settings: GenerationSettings; preset: string };
export type SecondSubject = { reference: ReferenceAsset | null; description: string };
export type Draft = {
  positive: string;
  negative: string;
  family: ReferenceFamily;
  parameters: Record<ReferenceFamily, FamilyDraft>;
  reference: ReferenceAsset | null;
  guidance: string;
  animaEngine: AnimaReferenceEngine;
  snaprefMode: SnapRefMode;
  description: string;
  second: SecondSubject | null;
  firstOnRight: boolean;
};
export const mossDefaults: GenerationSettings = {
  ...FAMILY_DEFAULTS.moss, family: 'moss', steps: 35, cfg: 3.5, scheduler: 'sgm_uniform', seed: -1, shift: undefined, moss_slg: false, loras: [],
};
const initialDraft = (): Draft => ({
  positive: '', negative: '', family: 'anima', reference: null, guidance: '4.5',
  animaEngine: 'anima_v2', snaprefMode: 'cs', description: '', second: null, firstOnRight: false,
  parameters: {
    anima: { settings: { ...FAMILY_DEFAULTS.anima, family: 'anima', seed: -1 }, preset: '' },
    moss: { settings: mossDefaults, preset: '' },
  },
});

const draftKey = (workId: string) => 'atelierx-reference-draft-' + workId;
const errorText = (error: unknown) => error instanceof ApiError ? tm(error.msg) : String(error);

function normalizeDraft(saved: (Partial<Draft> & Partial<FamilyDraft>) | null): Draft {
  const initial = initialDraft();
  if (!saved) return initial;
  return {
    positive: saved.positive ?? initial.positive,
    negative: saved.negative ?? initial.negative,
    reference: saved.reference ?? initial.reference,
    guidance: saved.guidance ?? initial.guidance,
    animaEngine: saved.animaEngine === 'snapref' ? 'snapref' : 'anima_v2',
    snaprefMode: saved.snaprefMode === 'char' ? 'char' : 'cs',
    description: saved.description ?? initial.description,
    second: saved.second ?? initial.second,
    firstOnRight: saved.firstOnRight === true,
    family: saved.family === 'moss' ? 'moss' : 'anima',
    parameters: {
      anima: {
        settings: { ...initial.parameters.anima.settings, ...(saved.parameters?.anima?.settings ?? saved.settings), family: 'anima' },
        preset: saved.parameters?.anima?.preset ?? saved.preset ?? '',
      },
      moss: {
        settings: { ...mossDefaults, ...saved.parameters?.moss?.settings },
        preset: saved.parameters?.moss?.preset ?? '',
      },
    },
  };
}

function loadDraft(workId: string): Draft {
  try {
    return normalizeDraft(JSON.parse(localStorage.getItem(draftKey(workId)) || 'null'));
  } catch {
    return initialDraft();
  }
}

type SavedDraft = ReferenceDraftFile<Draft>;

export function useReferenceDraft(workId: string | undefined, endpoint: string) {
  const [draft, setDraft] = useState(() => workId ? loadDraft(workId) : initialDraft());
  const [loaded, setLoaded] = useState(!!workId);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadError, setLoadError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [stored, setStored] = useState('');
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);
  const revision = useRef('');
  const serialized = JSON.stringify(draft);
  const dirty = loaded && stored !== serialized;

  useEffect(() => {
    if (workId) return;
    let current = true;
    setLoaded(false);
    setLoadError('');
    get<SavedDraft>(endpoint + '/draft').then(response => {
      if (!current) return;
      revision.current = response.revision;
      const next = normalizeDraft(response.draft);
      setDraft(next);
      setStored(JSON.stringify(next));
      setSaveError('');
      setLoaded(true);
    }).catch(error => { if (current) setLoadError(errorText(error)); });
    return () => { current = false; };
  }, [workId, endpoint, loadAttempt]);

  const save = useCallback(async () => {
    if (!loaded || inFlight.current) return false;
    if (workId) {
      try {
        localStorage.setItem(draftKey(workId), serialized);
        setStored(serialized);
        setSaveError('');
        return true;
      } catch {
        setSaveError(t('reference.storage_failed'));
        return false;
      }
    }
    inFlight.current = true;
    setSaving(true);
    try {
      const response = await put<SavedDraft>(endpoint + '/draft', {
        draft: { ...draft, schema_version: 1 }, revision: revision.current,
      });
      revision.current = response.revision;
      setStored(serialized);
      setSaveError('');
      return true;
    } catch (error) {
      setSaveError(errorText(error));
      return false;
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }, [draft, endpoint, loaded, serialized, workId]);

  useEffect(() => {
    if (!dirty || saving) return;
    if (workId) { void save(); return; }
    if (saveError) return;
    const timer = setTimeout(() => { void save(); }, 300);
    return () => clearTimeout(timer);
  }, [dirty, save, saveError, saving, workId]);

  const reload = () => setLoadAttempt(current => current + 1);
  return { draft, setDraft, loaded, dirty, loadError, saving, saveError, save, reload };
}
