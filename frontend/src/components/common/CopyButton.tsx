// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useState } from "react";
import { Button } from "../ui";

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    window.setTimeout(() => setState("idle"), 2000);
  };
  return (
    <Button size="sm" icon={state === "copied" ? "check" : "copy"} onClick={copy}>
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed — select the text" : label}
    </Button>
  );
}
