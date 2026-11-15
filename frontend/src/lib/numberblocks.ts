// SPDX-License-Identifier: AGPL-3.0-or-later

/** One number or block (first-last) per line (§4). A dash splits a block only
 * where both sides are whole numbers, so "573-555-0100" stays one number. */
export function parseNumbers(text: string): { first: string; last?: string }[] {
  const digits = (v: string) => v.replace(/\D/g, "").length;
  return text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
    const seps = /\s*(?:–|\bto\b|-)\s*/g;
    for (let m = seps.exec(l); m; m = seps.exec(l)) {
      const first = l.slice(0, m.index).trim();
      const last = l.slice(m.index + m[0].length).trim();
      if (digits(first) >= 7 && digits(last) >= 7) return { first, last };
    }
    return { first: l };
  });
}
