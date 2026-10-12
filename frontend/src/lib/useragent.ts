// SPDX-License-Identifier: AGPL-3.0-or-later
/** Turns a User-Agent string into "Browser on OS" for the sessions list (unit tested).
 *  Deliberately small: it names the common browsers and platforms and falls
 *  back to "Unknown device" rather than guessing. */

const BROWSERS: [RegExp, string][] = [
  [/\bEdg(?:e|A|iOS)?\/[\d.]+/, "Microsoft Edge"],
  [/\bOPR\/[\d.]+|\bOpera\b/, "Opera"],
  [/\bSamsungBrowser\/[\d.]+/, "Samsung Internet"],
  [/\bFirefox\/[\d.]+|\bFxiOS\/[\d.]+/, "Firefox"],
  [/\bChrome\/[\d.]+|\bCriOS\/[\d.]+/, "Chrome"],
  [/\bVersion\/[\d.]+.*\bSafari\//, "Safari"],
  [/\bcurl\/[\d.]+/, "curl"],
  [/\bpython-requests\/|\bpython-httpx\/|\btestclient\b/i, "Script"],
];

const PLATFORMS: [RegExp, string][] = [
  [/\biPhone\b|\biPod\b/, "iPhone"],
  [/\biPad\b/, "iPad"],
  [/\bAndroid\b/, "Android"],
  [/\bWindows NT\b/, "Windows"],
  [/\bMac OS X\b|\bMacintosh\b/, "macOS"],
  [/\bCrOS\b/, "ChromeOS"],
  [/\bLinux\b|\bX11\b/, "Linux"],
];

export interface DeviceDescription {
  browser: string | null;
  platform: string | null;
  label: string;
}

export function describeUserAgent(ua: string | null | undefined): DeviceDescription {
  if (!ua) return { browser: null, platform: null, label: "Unknown device" };
  const browser = BROWSERS.find(([re]) => re.test(ua))?.[1] ?? null;
  const platform = PLATFORMS.find(([re]) => re.test(ua))?.[1] ?? null;
  const label = browser && platform ? `${browser} on ${platform}` : (browser ?? platform ?? "Unknown device");
  return { browser, platform, label };
}
