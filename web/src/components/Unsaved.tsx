import { createContext, type ReactNode, useContext, useEffect, useMemo, useRef } from 'react';
import { UnsavedRegistry } from '../lib/unsaved';

// The register of unsaved changes (lib/unsaved.ts, #88) and the tab a screen is drawn in.
const Scope = createContext<{ registry: UnsavedRegistry; tab: string } | null>(null);

export function TabScope({ registry, tab, children }: { registry: UnsavedRegistry; tab: string; children: ReactNode }) {
  const value = useMemo(() => ({ registry, tab }), [registry, tab]);
  return <Scope.Provider value={value}>{children}</Scope.Provider>;
}

// A screen reports, under its own key, whether it has unsaved changes and how to save them (when it can be saved from
// outside, e.g. "Save all and leave"). Outside a tab (a dialog) it reports nowhere.
export function useUnsaved(key: string, dirty: boolean, save?: () => Promise<boolean>) {
  const scope = useContext(Scope);
  const saveRef = useRef(save);
  saveRef.current = save;
  const hasSave = !!save;
  useEffect(() => {
    scope?.registry.set(scope.tab, key, { dirty, save: hasSave ? () => saveRef.current!() : undefined });
  }, [scope, key, dirty, hasSave]);
  useEffect(() => () => scope?.registry.set(scope.tab, key, null), [scope, key]);
}
