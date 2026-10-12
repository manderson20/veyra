"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { IconButton } from "./Button";
import { Icon } from "./Icon";

type ToastKind = "success" | "error" | "info";
interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  text?: string;
}

interface ToastApi {
  show: (kind: ToastKind, title: string, text?: string) => void;
  success: (title: string, text?: string) => void;
  error: (title: string, text?: string) => void;
  info: (title: string, text?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);
  const show = useCallback(
    (kind: ToastKind, title: string, text?: string) => {
      const id = next.current++;
      setItems((all) => [...all.slice(-3), { id, kind, title, text }]);
      window.setTimeout(() => dismiss(id), kind === "error" ? 9000 : 5000);
    },
    [dismiss],
  );
  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (t, x) => show("success", t, x),
      error: (t, x) => show("error", t, x),
      info: (t, x) => show("info", t, x),
    }),
    [show],
  );
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" aria-live="polite" aria-relevant="additions">
        {items.map((t) => (
          <div key={t.id} className={`toast toast--${t.kind}`} role={t.kind === "error" ? "alert" : "status"}>
            <Icon name={t.kind === "success" ? "checkCircle" : t.kind === "error" ? "error" : "info"} />
            <div className="toast__body">
              <p className="toast__title">{t.title}</p>
              {t.text ? <p className="toast__text">{t.text}</p> : null}
            </div>
            <IconButton icon="x" label="Dismiss notification" size="sm" onClick={() => dismiss(t.id)} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}
