// SPDX-License-Identifier: AGPL-3.0-or-later
// After `next build`: the SHA-256 of every inline <script> the static export
// emits, so the installer can render a Content-Security-Policy without
// 'unsafe-inline' for scripts (docs/PRODUCTION_HARDENING.md §5).
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const out = process.argv[2] ?? "out";
const hashes = new Set();
function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (name.endsWith(".html")) {
      const html = readFileSync(p, "utf8");
      for (const m of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script\s*>/gi)) {
        if (m[1].trim()) hashes.add(`'sha256-${createHash("sha256").update(m[1]).digest("base64")}'`);
      }
    }
  }
}
walk(out);
writeFileSync(join(out, "csp-hashes.txt"), [...hashes].sort().join("\n") + (hashes.size ? "\n" : ""));
console.log(`csp-hashes: ${hashes.size} inline script hash(es)`);
