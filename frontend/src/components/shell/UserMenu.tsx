// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Icon, useToast } from "../ui";
import { api, errorMessage } from "@/lib/api";
import { initials } from "@/lib/format";
import { useSession } from "@/hooks/useSession";

export function UserMenu() {
  const { session, refresh } = useSession();
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
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
          <Link href="/account/" role="menuitem" className="menu__item" onClick={() => setOpen(false)}>
            <Icon name="key" size={16} /> Your account
          </Link>
          <button type="button" role="menuitem" className="menu__item" onClick={signOut}>
            <Icon name="logout" size={16} /> Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}
