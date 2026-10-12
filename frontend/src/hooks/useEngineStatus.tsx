// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { ApplyResult, ConfigRevision, DeployMode, EngineStatus } from "@/lib/types";
import { useApiData } from "./useApiData";
import { useSession } from "./useSession";

const REFRESH_MS = 15_000;
const POLL_MS = 2_000;
const POLL_LIMIT = 45; // 90 s
const IDLE_POLL_LIMIT = 10; // when waiting for calls to end, stop polling early and let the badge show it

interface EngineState {
  /** Null while loading or when the caller cannot read the engine status. */
  engine: EngineStatus | null;
  reload: () => void;
  /** Generate and deploy in one step (config.deploy). Resolves when the deployer reports. */
  apply: (mode?: DeployMode) => Promise<void>;
  applying: boolean;
  /** Increments after every finished apply so pages can refresh their data. */
  version: number;
}

const EngineContext = createContext<EngineState | null>(null);

/**
 * Shared engine status for the shell: the top-bar "Deploy changes" button and
 * the pending-change notices read from one poll instead of several.
 */
export function EngineStatusProvider({ children }: { children: ReactNode }) {
  const { can } = useSession();
  const toast = useToast();
  const data = useApiData<EngineStatus>(can("config.read") ? "/telephony/engine" : null);
  const [applying, setApplying] = useState(false);
  const [version, setVersion] = useState(0);
  const reload = data.reload;
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!can("config.read")) return;
    const t = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [can, reload]);

  const apply = useCallback(async (mode: DeployMode = "now") => {
    setApplying(true);
    try {
      const result = await api.post<ApplyResult>("/telephony/apply", { mode });
      const rev = result.revision;
      if (rev.state === "failed") {
        toast.error("Configuration could not be generated", rev.validation_errors[0]);
        return;
      }
      if (!result.applied) {
        toast.info("Nothing to apply", "The engine already runs the current configuration.");
        reload();
        return;
      }
      await new Promise<void>((resolve) => {
        let polls = 0;
        const tick = async () => {
          polls += 1;
          try {
            const r = await api.get<ConfigRevision>(`/telephony/revisions/${rev.id}`);
            if (r.state !== "deploying") {
              if (r.state === "deployed") toast.success(`Revision #${r.sequence} deployed`, "Phones will pick up the change.");
              else toast.error(`Revision #${r.sequence} failed`, r.validation_errors[0]);
              resolve();
              return;
            }
          } catch {
            /* keep polling */
          }
          if (mode === "when_idle" && polls >= IDLE_POLL_LIMIT) {
            toast.info("Waiting for calls to end", "The deployment runs as soon as no call is active. The top bar shows the wait.");
            resolve();
            return;
          }
          if (polls >= POLL_LIMIT) {
            toast.error("Still deploying", "The deployer has not reported yet. Check System → Telephony Engine.");
            resolve();
            return;
          }
          timer.current = window.setTimeout(() => void tick(), POLL_MS);
        };
        void tick();
      });
    } catch (err) {
      toast.error("Could not apply changes", errorMessage(err));
    } finally {
      setApplying(false);
      setVersion((v) => v + 1);
      reload();
    }
  }, [reload, toast]);

  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  const value = useMemo<EngineState>(
    () => ({ engine: data.data ?? null, reload, apply, applying, version }),
    [data.data, reload, apply, applying, version],
  );
  return <EngineContext.Provider value={value}>{children}</EngineContext.Provider>;
}

export function useEngineStatus(): EngineState {
  const ctx = useContext(EngineContext);
  if (!ctx) throw new Error("useEngineStatus must be used inside EngineStatusProvider");
  return ctx;
}
