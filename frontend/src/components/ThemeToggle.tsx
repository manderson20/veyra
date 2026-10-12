"use client";

import { useEffect } from "react";
import { IconButton } from "./ui";
import { applyTheme, asThemePreference, THEME_KEY, type ThemePreference } from "@/lib/theme";
import { useBrowserStore } from "@/hooks/useBrowserStore";

const ORDER: ThemePreference[] = ["system", "light", "dark"];
const META: Record<ThemePreference, { icon: string; label: string }> = {
  system: { icon: "monitor", label: "Theme: system" },
  light: { icon: "sun", label: "Theme: light" },
  dark: { icon: "moon", label: "Theme: dark" },
};

/** Current theme preference (saved in this browser), shared by every component. */
export function useThemePreference(): [ThemePreference, (p: ThemePreference) => void] {
  const [raw, setRaw] = useBrowserStore(THEME_KEY, "system");
  const pref = asThemePreference(raw);
  useEffect(() => {
    applyTheme(pref);
    if (pref !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [pref]);
  return [pref, (p: ThemePreference) => setRaw(p)];
}

export function ThemeToggle() {
  const [pref, choose] = useThemePreference();
  const next = ORDER[(ORDER.indexOf(pref) + 1) % ORDER.length] ?? "system";
  return (
    <IconButton icon={META[pref].icon} label={`${META[pref].label}. Switch to ${next}.`} onClick={() => choose(next)} />
  );
}
