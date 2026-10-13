// SPDX-License-Identifier: AGPL-3.0-or-later
/** The device label stored with the token ("Chrome on Windows"). */

interface UADataBrand {
  brand: string;
  version: string;
}

interface UAData {
  brands?: UADataBrand[];
  platform?: string;
}

type NavigatorWithUA = Navigator & { userAgentData?: UAData };

export function browserName(brands: readonly UADataBrand[] | undefined, userAgent: string): string {
  const names = (brands ?? []).map((b) => b.brand);
  if (names.some((n) => /Edge/i.test(n)) || /\bEdg\//.test(userAgent)) {
    return "Edge";
  }
  if (names.some((n) => /Google Chrome/i.test(n)) || /\bChrome\//.test(userAgent)) {
    return "Chrome";
  }
  if (names.some((n) => /Chromium/i.test(n))) {
    return "Chromium";
  }
  return "Browser";
}

export function platformName(platform: string | undefined, userAgent: string): string {
  const p = (platform ?? "").trim();
  if (p !== "" && p !== "Unknown") {
    return p;
  }
  if (/Windows/i.test(userAgent)) return "Windows";
  if (/Mac OS X|Macintosh/i.test(userAgent)) return "macOS";
  if (/CrOS/i.test(userAgent)) return "ChromeOS";
  if (/Android/i.test(userAgent)) return "Android";
  if (/Linux/i.test(userAgent)) return "Linux";
  return "an unknown OS";
}

export function deviceLabel(nav: Navigator = navigator): string {
  const data = (nav as NavigatorWithUA).userAgentData;
  const label = `${browserName(data?.brands, nav.userAgent)} on ${platformName(data?.platform, nav.userAgent)}`;
  return label.slice(0, 120);
}
