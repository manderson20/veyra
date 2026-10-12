/**
 * The only place branding artwork is referenced. Replace the files in
 * public/branding/ with approved artwork; no code changes are required.
 */
export const BRANDING = {
  logoLightBg: "/branding/logo-light-bg.svg",
  logoDarkBg: "/branding/logo-dark-bg.svg",
  icon: "/branding/icon.svg",
  favicon: "/branding/favicon.svg",
} as const;

/* eslint-disable @next/next/no-img-element -- static export; SVG artwork needs no optimization */

/** Logo that follows the current theme (light/dark artwork). */
export function BrandLogo({ height = 28, onDark = false }: { height?: number; onDark?: boolean }) {
  if (onDark) {
    return <img src={BRANDING.logoDarkBg} alt="Veyra" height={height} style={{ height, width: "auto" }} className="brand-logo" />;
  }
  return (
    <>
      <img src={BRANDING.logoLightBg} alt="Veyra" height={height} style={{ height, width: "auto" }} className="brand-logo brand-theme-light" />
      <img src={BRANDING.logoDarkBg} alt="Veyra" height={height} style={{ height, width: "auto" }} className="brand-logo brand-theme-dark" />
    </>
  );
}

export function BrandIcon({ size = 30 }: { size?: number }) {
  return <img src={BRANDING.icon} alt="Veyra" width={size} height={size} className="brand-icon" />;
}
