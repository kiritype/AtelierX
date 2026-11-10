import { createContext, useContext, useLayoutEffect, useSyncExternalStore, type ReactNode } from 'react';
import type { AppTheme, ThemePreference } from './types';

const SYSTEM_THEME_QUERY = '(prefers-color-scheme: dark)';
const ThemeContext = createContext<AppTheme>('light');

function subscribeToSystemTheme(onChange: () => void) {
  const query = window.matchMedia?.(SYSTEM_THEME_QUERY);
  query?.addEventListener('change', onChange);
  return () => query?.removeEventListener('change', onChange);
}

const ignoreSystemTheme = () => () => {};

export function AppThemeProvider({ preference, children }: { preference: ThemePreference; children: ReactNode }) {
  const theme = useSyncExternalStore<AppTheme>(
    preference === 'system' ? subscribeToSystemTheme : ignoreSystemTheme,
    () => preference === 'system'
      ? (window.matchMedia?.(SYSTEM_THEME_QUERY)?.matches ? 'dark' : 'light')
      : preference,
  );

  // The first screen waits for auth status. Apply the theme in the same commit, before that screen paints.
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
    return () => { delete document.documentElement.dataset.theme; };
  }, [theme]);

  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export const useAppTheme = () => useContext(ThemeContext);
