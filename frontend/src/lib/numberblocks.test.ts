// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { parseNumbers } from "./numberblocks";

describe("parseNumbers", () => {
  it("reads numbers and blocks, one per line", () => {
    expect(parseNumbers("5735550100\n\n 5735550200-5735550299 \n")).toEqual([
      { first: "5735550100" },
      { first: "5735550200", last: "5735550299" },
    ]);
  });
  it("keeps a dashed number whole", () => {
    expect(parseNumbers("573-555-0100")).toEqual([{ first: "573-555-0100" }]);
  });
  it("splits a block of dashed numbers", () => {
    expect(parseNumbers("573-555-0100 - 573-555-0199")).toEqual([{ first: "573-555-0100", last: "573-555-0199" }]);
    expect(parseNumbers("5735550100 to 5735550199")).toEqual([{ first: "5735550100", last: "5735550199" }]);
  });
});
