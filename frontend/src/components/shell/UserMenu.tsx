"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button, Callout, Dialog, Icon, TextField, useToast } from "../ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import { initials } from "@/lib/format";
import { useSession } from "@/hooks/useSession";
import { useOnChange } from "@/hooks/useOnChange";

export function UserMenu() {
  const { session, refresh } = useSession();
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!session) return null;
  const signOut = async () => {
    try {
      await api.post("/auth/logout");
    } catch (e) {
      toast.error("Sign-out failed", errorMessage(e));
      return;
    }
    await refresh();
    router.replace("/login/");
  };

  return (
    <div className="menu" ref={ref}>
      <button type="button" className="menu__trigger" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="avatar" aria-hidden="true">{initials(session.user.display_name)}</span>
        <span className="menu__trigger-name">{session.user.display_name}</span>
        <Icon name="chevronDown" size={14} />
      </button>
      {open ? (
        <div className="menu__list" role="menu" aria-label="Account">
          <div className="menu__header">
            <p style={{ fontWeight: 600 }}>{session.user.display_name}</p>
            <p className="subtle">{session.user.email}</p>
            {session.is_platform_admin ? <p className="subtle">Platform Administrator</p> : null}
          </div>
          <button type="button" role="menuitem" className="menu__item" onClick={() => { setOpen(false); setPwOpen(true); }}>
            <Icon name="key" size={16} /> Change password
          </button>
          <button type="button" role="menuitem" className="menu__item" onClick={signOut}>
            <Icon name="logout" size={16} /> Sign out
          </button>
        </div>
      ) : null}
      <ChangePasswordDialog open={pwOpen} onClose={() => setPwOpen(false)} />
    </div>
  );
}

function ChangePasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useOnChange(open, () => {
    if (open) {
      setCurrent("");
      setNext("");
      setConfirm("");
      setError(null);
    }
  });

  const mismatch = confirm.length > 0 && confirm !== next;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ message: string }>("/auth/password", { current_password: current, new_password: next });
      toast.success("Password changed", r.message);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail || err.title : errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      title="Change password"
      description="Your other sessions will be signed out."
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" type="submit" form="change-password" loading={busy} disabled={mismatch || !current || !next}>
            Change password
          </Button>
        </>
      }
    >
      <form id="change-password" onSubmit={submit} className="stack stack--sm">
        <TextField label="Current password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
        <TextField label="New password" type="password" autoComplete="new-password" required minLength={12} help="At least 12 characters." value={next} onChange={(e) => setNext(e.target.value)} />
        <TextField label="Confirm new password" type="password" autoComplete="new-password" required value={confirm} error={mismatch ? "Passwords do not match." : null} onChange={(e) => setConfirm(e.target.value)} />
        {error ? <Callout tone="danger">{error}</Callout> : null}
      </form>
    </Dialog>
  );
}
