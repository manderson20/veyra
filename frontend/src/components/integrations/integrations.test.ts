// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { curlExample, groupEvents, parseList } from "./IntegrationDialogs";
import { parseDomains } from "./ProviderDialog";

describe("integrations helpers", () => {
  it("parses domains, dropping @, case and duplicates", () => {
    expect(parseDomains(" Example.org, @example.org\nschools.example.net;")).toEqual(["example.org", "schools.example.net"]);
    expect(parseDomains("   ")).toEqual([]);
  });

  it("parses address lists", () => {
    expect(parseList("10.0.0.0/8, 192.168.1.20\n192.168.1.20")).toEqual(["10.0.0.0/8", "192.168.1.20"]);
  });

  it("groups the event catalog in order", () => {
    const groups = groupEvents([
      { name: "call.ringing", group: "Calls", description: "", live: true, module: null },
      { name: "page.sent", group: "Paging", description: "", live: false, module: null },
      { name: "call.ended", group: "Calls", description: "", live: false, module: null },
    ]);
    expect(groups.map((g) => [g.group, g.events.map((e) => e.name)])).toEqual([
      ["Calls", ["call.ringing", "call.ended"]],
      ["Paging", ["page.sent"]],
    ]);
  });

  it("shows how to send a page with the token", () => {
    expect(curlExample("https://veyra.example", "vyi_x")).toContain('-H "Authorization: Bearer vyi_x"');
  });
});
