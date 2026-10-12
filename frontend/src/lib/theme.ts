export type ThemePreference = "system" | "light" | "dark";
export const THEME_KEY = "veyra.theme";

export function resolveTheme(pref: ThemePreference): "light" | "dark" {
  if (pref !== "system") return pref;
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function applyTheme(pref: ThemePreference): void {
  document.documentElement.dataset.theme = resolveTheme(pref);
}

export function asThemePreference(value: string | null): ThemePreference {
  return value === "light" || value === "dark" || value === "system" ? value : "system";
}

/** Inline script run before first paint so the page never flashes the wrong theme. */
export const THEME_BOOTSTRAP = `(function(){try{var p=localStorage.getItem('${THEME_KEY}')||'system';var d=p==='dark'||(p==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.dataset.theme=d?'dark':'light';}catch(e){document.documentElement.dataset.theme='light';}})();`;
