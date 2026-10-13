// SPDX-License-Identifier: AGPL-3.0-or-later
// Renders the extension icons: a rounded square in Veyra teal with a white
// "V". Pure Node (zlib + a small PNG encoder), so no binary assets need to be
// committed. `node scripts/icons.mjs` writes icons/icon-<size>.png; the Vite
// build calls renderIcon() and emits the files into dist/icons/.
import { deflateSync } from "node:zlib";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const SIZES = [16, 32, 48, 128];
const TEAL = [0x0f, 0x76, 0x6e];
const WHITE = [0xff, 0xff, 0xff];

const CRC_TABLE = new Int32Array(256);
for (let n = 0; n < 256; n += 1) {
  let c = n;
  for (let k = 0; k < 8; k += 1) {
    c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  }
  CRC_TABLE[n] = c;
}

export function crc32(buffer) {
  let crc = -1;
  for (const byte of buffer) {
    crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ -1) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const typeAndData = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(typeAndData));
  return Buffer.concat([length, typeAndData, crc]);
}

/** Encode RGBA pixels as a PNG file. */
export function encodePng(width, height, rgba) {
  const stride = width * 4;
  const raw = Buffer.alloc((stride + 1) * height);
  for (let y = 0; y < height; y += 1) {
    raw[y * (stride + 1)] = 0; // filter: none
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // colour type RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function insideRoundedSquare(x, y, size) {
  const r = size * 0.22;
  const min = r;
  const max = size - r;
  const cx = x < min ? min : x > max ? max : x;
  const cy = y < min ? min : y > max ? max : y;
  const dx = x - cx;
  const dy = y - cy;
  return dx * dx + dy * dy <= r * r;
}

function distanceToSegment(px, py, ax, ay, bx, by) {
  const vx = bx - ax;
  const vy = by - ay;
  const wx = px - ax;
  const wy = py - ay;
  const len2 = vx * vx + vy * vy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, (wx * vx + wy * vy) / len2));
  const cx = ax + t * vx;
  const cy = ay + t * vy;
  return Math.hypot(px - cx, py - cy);
}

function insideGlyph(x, y, size) {
  // The letter V: two strokes meeting at the bottom centre.
  const half = size * 0.065;
  const top = size * 0.3;
  const bottom = size * 0.72;
  const left = size * 0.3;
  const right = size * 0.7;
  const mid = size * 0.5;
  return (
    distanceToSegment(x, y, left, top, mid, bottom) <= half ||
    distanceToSegment(x, y, right, top, mid, bottom) <= half
  );
}

/** Render one icon as a PNG buffer (4x4 supersampling for smooth edges). */
export function renderIcon(size) {
  const samples = 4;
  const rgba = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      let coverage = 0;
      let glyph = 0;
      for (let sy = 0; sy < samples; sy += 1) {
        for (let sx = 0; sx < samples; sx += 1) {
          const px = x + (sx + 0.5) / samples;
          const py = y + (sy + 0.5) / samples;
          if (insideRoundedSquare(px, py, size)) {
            coverage += 1;
            if (insideGlyph(px, py, size)) glyph += 1;
          }
        }
      }
      const total = samples * samples;
      const alpha = Math.round((coverage / total) * 255);
      const g = coverage === 0 ? 0 : glyph / coverage;
      const offset = (y * size + x) * 4;
      for (let c = 0; c < 3; c += 1) {
        rgba[offset + c] = Math.round(TEAL[c] * (1 - g) + WHITE[c] * g);
      }
      rgba[offset + 3] = alpha;
    }
  }
  return encodePng(size, size, rgba);
}

export function iconFileName(size) {
  return `icons/icon-${size}.png`;
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  mkdirSync(join(root, "icons"), { recursive: true });
  for (const size of SIZES) {
    const file = join(root, iconFileName(size));
    writeFileSync(file, renderIcon(size));
    console.log(`wrote ${file}`);
  }
}
