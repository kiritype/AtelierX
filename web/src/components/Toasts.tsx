import { createContext, useCallback, useContext, useState } from 'react';

type Toast = { id: number; text: string; action?: { label: string; run: () => void }; tone?: 'error' };
type Ctx = { toasts: Toast[]; push: (toast: Omit<Toast, 'id'>) => void; dismiss: (id: number) => void };

const ToastContext = createContext<Ctx>({ toasts: [], push: () => {}, dismiss: () => {} });
let seq = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts((list) => list.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (toast: Omit<Toast, 'id'>) => {
      const id = ++seq;
      setToasts((list) => [...list.slice(-3), { ...toast, id }]);
      setTimeout(() => dismiss(id), 6000);
    },
    [dismiss],
  );
  return <ToastContext.Provider value={{ toasts, push, dismiss }}>{children}</ToastContext.Provider>;
}

export const useToast = () => useContext(ToastContext).push;

export function Toasts() {
  const { toasts, dismiss } = useContext(ToastContext);
  return (
    <div className="toasts">
      {toasts.map((toast) => (
        <div key={toast.id} className="toast" style={toast.tone === 'error' ? { color: 'var(--danger)' } : undefined}>
          <span className="grow">{toast.text}</span>
          {toast.action && (
            <button
              onClick={() => {
                toast.action!.run();
                dismiss(toast.id);
              }}
            >
              {toast.action.label}
            </button>
          )}
          <button className="ghost" onClick={() => dismiss(toast.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
