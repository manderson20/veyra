// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * The only place branding artwork is referenced. The files live in
 * public/branding/ (see its README for what each one is for). The artwork is
 * raster (PNG/ICO) exported from the approved logo, so every image carries its
 * native dimensions and is scaled by CSS with the aspect ratio kept.
 */
export const BRANDING = {
  /** Icon + wordmark, no tagline: navigation and other compact placements. */
  logoCompact: {
    lightBg: "/branding/logo-compact-light.png",
    darkBg: "/branding/logo-compact-dark.png",
    width: 2200,
    height: 620,
  },
  /** Icon + wordmark + tagline: larger placements such as the sign-in aside. */
  logoFull: {
    lightBg: "/branding/logo-light.png",
    darkBg: "/branding/logo-dark.png",
    width: 2200,
    height: 700,
  },
  /** The V emblem alone, transparent, square. */
  icon: "/branding/icon.png",
  /** The emblem on a rounded navy tile (installable app icon). */
  appIcon: "/branding/app-icon.png",
  favicon: "/branding/favicon.ico",
  favicon32: "/branding/favicon-32.png",
  appleTouchIcon: "/branding/apple-touch-icon.png",
} as const;

/* eslint-disable @next/next/no-img-element -- static export; the artwork is served as-is */

type LogoVariant = "compact" | "full";

function logoImg(src: string, variant: LogoVariant, height: number, className: string) {
  const art = variant === "full" ? BRANDING.logoFull : BRANDING.logoCompact;
  // Explicit width/height attributes give the browser the aspect ratio before
  // the image loads, so the layout does not shift.
  return (
    <img
      src={src}
      alt="Veyra"
      width={art.width}
      height={art.height}
      decoding="async"
      style={{ display: "block", height, width: "auto", maxWidth: "100%", objectFit: "contain" }}
      className={className}
    />
  );
}

/**
 * Logo that follows the current theme. `onDark` forces the dark-background
 * artwork for surfaces that are navy in both themes (sidebar, sign-in aside).
 */
export function BrandLogo({
  height = 28,
  onDark = false,
  variant = "compact",
}: {
  height?: number;
  onDark?: boolean;
  variant?: LogoVariant;
}) {
  const art = variant === "full" ? BRANDING.logoFull : BRANDING.logoCompact;
  if (onDark) {
    return logoImg(art.darkBg, variant, height, "brand-logo");
  }
  return (
    <>
      {logoImg(art.lightBg, variant, height, "brand-logo brand-theme-light")}
      {logoImg(art.darkBg, variant, height, "brand-logo brand-theme-dark")}
    </>
  );
}

export function BrandIcon({ size = 30 }: { size?: number }) {
  return (
    <img
      src={BRANDING.icon}
      alt="Veyra"
      width={size}
      height={size}
      decoding="async"
      style={{ display: "block", objectFit: "contain" }}
      className="brand-icon"
    />
  );
}
