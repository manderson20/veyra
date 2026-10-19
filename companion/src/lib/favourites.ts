// SPDX-License-Identifier: AGPL-3.0-or-later
/** Favourite contacts as one-touch dial buttons (issue #128): the user's
 * contacts marked favourite on My Phone (`GET /me/contacts?favourite=true`)
 * replace the Companion's own speed dials. */

export interface ContactNumber {
  label: string;
  number: string;
}

/** The fields of a `GET /me/contacts` row the Companion uses. */
export interface MyContact {
  id: string;
  name: string;
  numbers: ContactNumber[];
  favourite: boolean;
  speed_dial: number | null;
}

export interface Favourite {
  label: string;
  number: string;
  slot: number | null;
}

const ORDER = ["work", "mobile", "home", "other"];

/** One button per favourite with a number: speed-dial slot order first, then
 * by name; the work number before mobile, home and other. */
export function favouritesFrom(contacts: MyContact[]): Favourite[] {
  const out: Favourite[] = [];
  for (const c of contacts) {
    if (!c.favourite) continue;
    const numbers = [...c.numbers].sort((a, b) => rank(a.label) - rank(b.label));
    const first = numbers[0];
    if (!first) continue;
    out.push({ label: c.name, number: first.number, slot: c.speed_dial });
  }
  return out.sort(
    (a, b) => (a.slot ?? 1000) - (b.slot ?? 1000) || a.label.localeCompare(b.label),
  );
}

function rank(label: string): number {
  const i = ORDER.indexOf(label);
  return i === -1 ? ORDER.length : i;
}
