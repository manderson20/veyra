// SPDX-License-Identifier: AGPL-3.0-or-later
/** Number handling (docs/COMPANION.md §5): digits, `*`, `#` and a leading `+`
 * are kept; everything typed around them (spaces, dots, dashes, parentheses)
 * is dropped. Numbers longer than an extension get the user's dial prefix
 * unless they already carry it; `+1` becomes the prefix followed by `1`.
 * The server validates again and the outbound routes decide what is dialable. */

export interface NormalizeOptions {
  dialPrefix: string;
  extensionLength?: number;
}

export const DEFAULT_EXTENSION_LENGTH = 4;

/** Strip decoration and return `+`-prefixed-or-not digits, `*` and `#`. */
export function cleanNumber(raw: string): string {
  const trimmed = raw.trim();
  const plus = trimmed.startsWith("+");
  const body = trimmed.replace(/[^0-9*#]/g, "");
  return plus ? `+${body}` : body;
}

export function normalizeNumber(raw: string, options: NormalizeOptions): string {
  const prefix = options.dialPrefix.replace(/[^0-9]/g, "");
  const extensionLength = options.extensionLength ?? DEFAULT_EXTENSION_LENGTH;
  const cleaned = cleanNumber(raw);
  if (cleaned === "" || cleaned === "+") {
    return "";
  }
  if (cleaned.startsWith("+1") && cleaned.length === 12) {
    return `${prefix}1${cleaned.slice(2)}`;
  }
  if (cleaned.startsWith("+")) {
    return `${prefix}${cleaned.slice(1)}`;
  }
  // Feature codes (*43, #31#) are never external numbers.
  if (cleaned.startsWith("*") || cleaned.startsWith("#")) {
    return cleaned;
  }
  if (cleaned.length > extensionLength && prefix !== "" && !cleaned.startsWith(prefix)) {
    return `${prefix}${cleaned}`;
  }
  return cleaned;
}

/** Is the selected text plausibly a phone number? At least three digits and
 * nothing but digits, `*`, `#`, `+` and the usual decoration. */
export function looksLikeNumber(text: string): boolean {
  const trimmed = text.trim();
  if (trimmed.length === 0 || trimmed.length > 64) {
    return false;
  }
  if (!/^[0-9*#+\s().\-‐-― ]+$/.test(trimmed)) {
    return false;
  }
  const digits = trimmed.replace(/[^0-9]/g, "");
  return digits.length >= 3 && digits.length <= 32;
}
