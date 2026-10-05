import { createContext, useContext, useEffect } from 'react';

// Forms in the settings tab that keep typed values until Save report whether they have unsaved changes, each under its
// own key, so saving one form never clears another's mark. The tab asks before closing while any key is dirty.
export const SettingsDirty = createContext<(key: string, dirty: boolean) => void>(() => undefined);

export function useReportDirty(key: string, dirty: boolean) {
  const report = useContext(SettingsDirty);
  useEffect(() => report(key, dirty), [key, dirty, report]);
  useEffect(() => () => report(key, false), [key, report]);
}
