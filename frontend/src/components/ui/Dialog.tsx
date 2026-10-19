// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Button, IconButton } from "./Button";
import { TextField } from "./Form";
import { Callout } from "./Feedback";
import { useOnChange } from "@/hooks/useOnChange";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "md" | "lg";
  /** "inner": the body never scrolls; a child marked to fill takes the remaining height and scrolls itself (one scroll bar). */
  scroll?: "body" | "inner";
  variant?: "dialog" | "drawer";
  /** Prevent closing (e.g. while a request is in flight). */
  busy?: boolean;
}

/**
 * Modal dialog on the native <dialog> element: the browser provides the focus
 * trap, inert background and Esc handling. Focus returns to the opener on close.
 */
export function Dialog({ open, onClose, title, description, children, footer, size = "md", variant = "dialog", busy, scroll = "body" }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descId = useId();
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) {
      opener.current = document.activeElement;
      el.showModal();
    } else if (!open && el.open) {
      el.close();
      if (opener.current instanceof HTMLElement) opener.current.focus();
    }
  }, [open]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onCancel = (e: Event) => {
      e.preventDefault();
      if (!busy) onClose();
    };
    el.addEventListener("cancel", onCancel);
    return () => el.removeEventListener("cancel", onCancel);
  }, [busy, onClose]);

  const cls = ["dialog", size === "lg" && "dialog--lg", variant === "drawer" && "drawer", scroll === "inner" && "dialog--inner-scroll"].filter(Boolean).join(" ");
  return (
    <dialog
      ref={ref}
      className={cls}
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      onClick={(e) => {
        if (e.target === ref.current && !busy) onClose();
      }}
    >
      {open ? (
        <>
          <div className="dialog__header">
            <div>
              <h2 className="dialog__title" id={titleId}>{title}</h2>
              {description ? <p className="dialog__description" id={descId}>{description}</p> : null}
            </div>
            <IconButton icon="x" label="Close" onClick={onClose} disabled={busy} size="sm" />
          </div>
          <div className="dialog__body">{children}</div>
          {footer ? <div className="dialog__footer">{footer}</div> : null}
        </>
      ) : null}
    </dialog>
  );
}

interface ConfirmDialogProps {
  open: boolean;
  title: ReactNode;
  children?: ReactNode;
  confirmLabel?: string;
  tone?: "danger" | "primary";
  /** When set, the user must type this exact text to enable the confirm button. */
  typeToConfirm?: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = "Confirm",
  tone = "primary",
  typeToConfirm,
  busy,
  error,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState("");
  useOnChange(open, () => setTyped(""));
  const blocked = typeToConfirm !== undefined && typed !== typeToConfirm;
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      busy={busy}
      footer={
        <>
          <Button onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button variant={tone} onClick={onConfirm} loading={busy} disabled={blocked}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
      {typeToConfirm !== undefined ? (
        <TextField
          label={<>Type <code>{typeToConfirm}</code> to confirm</>}
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
      ) : null}
      {error ? <Callout tone="danger">{error}</Callout> : null}
    </Dialog>
  );
}
