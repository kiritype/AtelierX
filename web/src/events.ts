// Server -> UI event stream (/api/events).
import { useEffect } from 'react';

export type ServerEvent = { type: string; data: any };

export function useServerEvents(enabled: boolean, onEvent: (event: ServerEvent) => void) {
  useEffect(() => {
    if (!enabled) return;
    const source = new EventSource('/api/events');
    source.onmessage = (message) => {
      try {
        onEvent(JSON.parse(message.data));
      } catch {
        /* ignore malformed events */
      }
    };
    return () => source.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);
}
