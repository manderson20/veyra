// SPDX-License-Identifier: AGPL-3.0-or-later

export function sameBrand(a: string | null | undefined, b: string | null | undefined): boolean {
  return !!a && !!b && a.toLowerCase() === b.toLowerCase();
}

/** Rows under their brand, brands in alphabetical order, rows in their given order. */
export function groupByBrand<T>(rows: T[], brandOf: (row: T) => string | null | undefined): { brand: string; rows: T[] }[] {
  const groups = new Map<string, { brand: string; rows: T[] }>();
  for (const row of rows) {
    const brand = brandOf(row) || "Other";
    const key = brand.toLowerCase();
    const group = groups.get(key);
    if (group) group.rows.push(row);
    else groups.set(key, { brand, rows: [row] });
  }
  return [...groups.values()].sort((a, b) => a.brand.localeCompare(b.brand));
}
