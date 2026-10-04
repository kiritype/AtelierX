import { useEffect, useRef, useState } from 'react';
import { t } from '../i18n';
import type { FromFrame, GlobalStub, ToFrame } from '../preview/protocol';

export type PreviewCall = { name: string; args: unknown[] };

const TIMEOUT_MS = 3000;
const IDENTIFIER = /^[\p{L}_$][\p{L}\p{N}_$]*$/u;

// Sandboxed component preview (07-jsx: 미리보기 실행). A frame that stops answering is replaced.
export default function JsxPreview({
  code,
  name,
  props,
  hooks,
  globals,
  theme = 'light',
  width,
  autoHeight = false,
  onCall,
  onError,
}: {
  code: string;
  name: string;
  props: unknown;
  hooks: string[];
  globals: GlobalStub[];
  theme?: 'light' | 'dark' | 'inline';
  width?: number;
  autoHeight?: boolean;
  onCall?: (call: PreviewCall) => void;
  onError?: (error: { message: string; line: number | null } | null) => void;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [generation, setGeneration] = useState(0);
  const [ready, setReady] = useState(false);
  const [height, setHeight] = useState(60);
  const [error, setError] = useState<{ message: string; line: number | null } | null>(null);
  const [hung, setHung] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const pending = useRef<{ id: number; timer: number } | null>(null);
  const nextId = useRef(1);
  const latest = useRef(0);
  const failed = useRef(0);
  const callbacks = useRef({ onCall, onError });
  callbacks.current = { onCall, onError };

  useEffect(() => {
    const listen = (event: MessageEvent) => {
      if (!frame.current || event.source !== frame.current.contentWindow) return;
      const message = event.data as FromFrame;
      if (message.type === 'ready') setReady(true);
      if (message.type === 'size' && autoHeight) setHeight(Math.max(24, Math.ceil(message.height)));
      if (message.type === 'call') callbacks.current.onCall?.({ name: message.name, args: message.args });
      if (message.type !== 'rendered' && message.type !== 'error') return;
      if (message.id !== latest.current) return;
      if (pending.current?.id === message.id) {
        clearTimeout(pending.current.timer);
        pending.current = null;
      }
      // An error (also one thrown later, e.g. in an effect) wins over the 'rendered' that follows it.
      if (message.type === 'error') failed.current = message.id;
      else if (failed.current === message.id) return;
      const next = message.type === 'error' ? { message: message.message, line: message.line } : null;
      setError(next);
      callbacks.current.onError?.(next);
    };
    window.addEventListener('message', listen);
    return () => window.removeEventListener('message', listen);
  }, [autoHeight]);

  // Some embedded browsers refuse sandboxed frames; say so instead of showing an empty box.
  useEffect(() => {
    if (ready) return;
    const timer = window.setTimeout(() => setUnavailable(true), 5000);
    return () => clearTimeout(timer);
  }, [ready, generation]);
  useEffect(() => {
    if (ready) setUnavailable(false);
  }, [ready]);

  // Parents pass fresh objects each render; send again only when the content changes.
  const payload = JSON.stringify({ code, name, props, hooks, globals, theme });
  useEffect(() => {
    if (!ready || !frame.current?.contentWindow) return;
    const { code, name, props, hooks, globals, theme } = JSON.parse(payload) as Omit<ToFrame, 'type' | 'id'>;
    if (!IDENTIFIER.test(name)) {
      const next = { message: t('jsx.bad_name', { name }), line: null };
      setError(next);
      callbacks.current.onError?.(next);
      return;
    }
    const id = nextId.current++;
    latest.current = id;
    if (pending.current) clearTimeout(pending.current.timer);
    const timer = window.setTimeout(() => {
      pending.current = null;
      setHung(true);
      setReady(false);
      setGeneration((g) => g + 1);
    }, TIMEOUT_MS);
    pending.current = { id, timer };
    const message: ToFrame = { type: 'render', id, code, name, props, hooks, globals, theme };
    frame.current.contentWindow.postMessage(message, '*');
  }, [ready, payload]);

  useEffect(
    () => () => {
      if (pending.current) clearTimeout(pending.current.timer);
    },
    [],
  );

  return (
    <div className="jsx-preview" style={{ width: width ?? '100%' }}>
      {hung && (
        <div className="warn-text">
          {t('jsx.restarted')}{' '}
          <a href="#" onClick={(e) => (e.preventDefault(), setHung(false))}>
            ×
          </a>
        </div>
      )}
      {unavailable && <div className="warn-text">{t('jsx.unavailable')}</div>}
      {error && (
        <div className="preview-error-box">
          {error.line ? `${t('jsx.line', { n: error.line })} · ` : ''}
          {error.message}
        </div>
      )}
      <iframe
        key={generation}
        ref={frame}
        title={name}
        src="/preview.html"
        sandbox="allow-scripts"
        style={{ width: '100%', height: autoHeight ? height : '100%', border: 0, display: 'block', background: 'transparent' }}
      />
    </div>
  );
}
