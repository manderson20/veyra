// SPDX-License-Identifier: AGPL-3.0-or-later
/** The forms render their conditional fields (no browser: server rendering). */
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { KeyListEditor } from "@/components/devices/KeyListEditor";
import { EMPTY_QUEUE, QueueFields } from "@/components/groups/QueueFields";
import { EMPTY_DESTINATION } from "@/lib/routing";
import { EMPTY_INBOUND_ROUTE, InboundRouteFields, inboundRouteBody, inboundRouteValid } from "./InboundRouteFields";
import { EMPTY_OUTBOUND_ROUTE, OutboundRouteFields } from "./OutboundRouteFields";
import { EMPTY_TIME_CONDITION, TimeConditionFields } from "./TimeConditionFields";

vi.mock("@/hooks/useSession", () => ({ useSession: () => ({ session: null, can: () => true, canAny: () => true, hasPermission: () => true }) }));

const noop = () => undefined;

describe("forms with options added for #142", () => {
  it("inbound route: caller rules", () => {
    const draft = {
      ...EMPTY_INBOUND_ROUTE,
      caller_rules: [
        { match: "anonymous" as const, number: "", destination: EMPTY_DESTINATION },
        { match: "prefix" as const, number: "573", destination: EMPTY_DESTINATION },
      ],
    };
    const html = renderToString(createElement(InboundRouteFields, { draft, onChange: noop, errors: {}, organizationId: "o" }));
    expect(html).toContain("Rule 2: send to");
    expect(html).toContain("Add caller rule");
    expect(html.match(/value="hangup"/g)?.length).toBe(2);
    // A number field only where the rule needs one.
    expect(html.match(/>Number</g)?.length).toBe(1);
    expect(inboundRouteBody(draft).caller_rules?.map((c) => c.number)).toEqual([null, "573"]);
    expect(inboundRouteValid({ ...draft, did: "5735550100" })).toBe(false);
  });

  it("outbound route: hours only for one organization, never emergency", () => {
    const render = (patch: object) => renderToString(createElement(OutboundRouteFields, { draft: { ...EMPTY_OUTBOUND_ROUTE, ...patch }, onChange: noop, errors: {}, trunks: [] }));
    const label = "Only while this time condition is open";
    expect(render({ organization_id: "o" })).toContain(label);
    expect(render({})).not.toContain(label);
    expect(render({ organization_id: "o", is_emergency: true })).not.toContain(label);
  });

  it("time condition: the title filter follows the calendar", () => {
    const render = (patch: object) => renderToString(createElement(TimeConditionFields, { draft: { ...EMPTY_TIME_CONDITION, ...patch }, onChange: noop, errors: {}, organizationId: "o" }));
    expect(render({})).toContain("Closed during events of a calendar");
    expect(render({})).not.toContain("Only events whose title contains");
    expect(render({ closed_calendar_id: "c" })).toContain("Only events whose title contains");
  });

  it("queue: wait options", () => {
    const html = renderToString(createElement(QueueFields, { draft: { ...EMPTY_QUEUE, announce_holdtime: true }, onChange: noop, errors: {} } as never));
    expect(html).toContain("Announce the expected wait");
    expect(html).toContain("Announce every (seconds)");
    expect(html).toContain("Delay before connecting the agent");
  });

  it("phone keys: the record key has no target", () => {
    const html = renderToString(createElement(KeyListEditor, { keys: [{ type: "record", value: "", label: null }], onChange: noop, zones: [] } as never));
    expect(html).toContain("Record this call");
    expect(html).toContain("starts recording");
  });
});
