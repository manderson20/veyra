// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { resolveTab, withTab } from "./tabs";

const IDS = ["general", "callerid", "phones"];

describe("URL-addressed tabs", () => {
  it("resolves the tab the URL names and falls back otherwise", () => {
    expect(resolveTab("phones", IDS, "general")).toBe("phones");
    expect(resolveTab(null, IDS, "general")).toBe("general");
    expect(resolveTab(undefined, IDS, "general")).toBe("general");
    expect(resolveTab("nope", IDS, "general")).toBe("general");
    expect(resolveTab("", IDS, "general")).toBe("general");
  });

  it("writes the tab into the query string and keeps the other parameters", () => {
    expect(withTab("id=abc", "phones", "general")).toBe("id=abc&tab=phones");
    expect(withTab("id=abc&tab=phones", "callerid", "general")).toBe("id=abc&tab=callerid");
    expect(withTab("id=abc&tab=phones", "general", "general")).toBe("id=abc");
    expect(withTab("", "general", "general")).toBe("");
  });
});
