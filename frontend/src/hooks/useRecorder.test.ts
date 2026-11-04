// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { blobToBase64 } from "./useRecorder";

describe("blobToBase64", () => {
  it("encodes bytes without a data: prefix", async () => {
    expect(await blobToBase64(new Blob([new Uint8Array([0, 1, 2, 250, 255])]))).toBe("AAEC+v8=");
  });
  it("handles recordings larger than one chunk", async () => {
    const bytes = new Uint8Array(0x8000 * 2 + 3).fill(65);
    const out = await blobToBase64(new Blob([bytes]));
    expect(atob(out).length).toBe(bytes.length);
  });
});
