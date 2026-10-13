// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { parseStreamEvent, type CallEndedEvent, type CallRingingEvent } from "./events";
import { applyToRecent, notificationFor, notificationsToClear } from "./notifications";
import type { RecentCall } from "./types";

const base = {
  channel_id: "PJSIP/acme-1001-00000001",
  extension_id: "e1",
  extension_number: "1001",
  remote_number: "5735550100",
  remote_name: "Pat Example",
  at: "2026-10-13T14:00:00+00:00",
  answered: false,
  cause: null,
};

const ringing: CallRingingEvent = { type: "call.ringing", direction: "in", ...base };
const ended: CallEndedEvent = { type: "call.ended", direction: "in", ...base, cause: "normal" };
const allOn = { notify_incoming: true, notify_missed: true };

describe("notificationFor", () => {
  it("announces an incoming call", () => {
    const intent = notificationFor(ringing, allOn);
    expect(intent).toMatchObject({
      kind: "incoming",
      title: "Incoming call on 1001",
      message: "Pat Example 5735550100",
      callback: null,
    });
  });

  it("stays quiet when incoming notifications are off", () => {
    expect(notificationFor(ringing, { notify_incoming: false, notify_missed: true })).toBeNull();
  });

  it("ignores outgoing ringing", () => {
    expect(notificationFor({ ...ringing, direction: "out" }, allOn)).toBeNull();
    expect(notificationFor({ ...ringing, type: "call.dialing", direction: "out" }, allOn)).toBeNull();
  });

  it("reports a missed call with a call-back number", () => {
    const intent = notificationFor(ended, allOn);
    expect(intent).toMatchObject({
      kind: "missed",
      title: "Missed call on 1001",
      message: "Pat Example 5735550100",
      callback: "5735550100",
    });
  });

  it("does not report answered or outgoing calls as missed", () => {
    expect(notificationFor({ ...ended, answered: true }, allOn)).toBeNull();
    expect(notificationFor({ ...ended, direction: "out" }, allOn)).toBeNull();
  });

  it("stays quiet when missed notifications are off", () => {
    expect(notificationFor(ended, { notify_incoming: true, notify_missed: false })).toBeNull();
  });

  it("falls back to the number or a placeholder when the name is missing", () => {
    expect(notificationFor({ ...ringing, remote_name: null }, allOn)?.message).toBe("5735550100");
    expect(
      notificationFor({ ...ringing, remote_name: null, remote_number: null }, allOn)?.message,
    ).toBe("Unknown number");
    expect(notificationFor({ ...ended, remote_number: null }, allOn)?.callback).toBeNull();
  });

  it("does nothing for hello, ping and answered", () => {
    expect(
      notificationFor({ type: "hello", extensions: [], listener: "connected", server_time: "" }, allOn),
    ).toBeNull();
    expect(notificationFor({ type: "ping", listener: "connected" }, allOn)).toBeNull();
    expect(notificationFor({ ...ringing, type: "call.answered" }, allOn)).toBeNull();
  });
});

describe("notificationsToClear", () => {
  it("clears the incoming toast when the call is answered or over", () => {
    const id = notificationFor(ringing, allOn)?.id;
    expect(notificationsToClear({ ...ringing, type: "call.answered" })).toEqual([id]);
    expect(notificationsToClear(ended)).toEqual([id]);
    expect(notificationsToClear(ringing)).toEqual([]);
  });
});

describe("applyToRecent", () => {
  it("records a call and updates it as it progresses", () => {
    let recent: RecentCall[] = [];
    recent = applyToRecent(recent, ringing);
    expect(recent).toHaveLength(1);
    expect(recent[0]).toMatchObject({ number: "5735550100", direction: "in", answered: false });
    recent = applyToRecent(recent, { ...ringing, type: "call.answered" });
    expect(recent[0]?.answered).toBe(true);
    recent = applyToRecent(recent, { ...ended, answered: true });
    expect(recent).toHaveLength(1);
    expect(recent[0]?.answered).toBe(true);
  });

  it("keeps the newest first and at most twenty", () => {
    let recent: RecentCall[] = [];
    for (let i = 0; i < 25; i += 1) {
      recent = applyToRecent(recent, { ...ringing, channel_id: `c${i}`, remote_number: `${i}` });
    }
    expect(recent).toHaveLength(20);
    expect(recent[0]?.channel_id).toBe("c24");
  });

  it("records an ended call whose start was missed", () => {
    const recent = applyToRecent([], ended);
    expect(recent).toHaveLength(1);
    expect(recent[0]?.answered).toBe(false);
  });
});

describe("parseStreamEvent", () => {
  it("parses the server's frames", () => {
    expect(parseStreamEvent('{"type":"ping","listener":"reconnecting"}')).toEqual({
      type: "ping",
      listener: "reconnecting",
    });
    const hello = parseStreamEvent(
      '{"type":"hello","extensions":[{"id":"e1","number":"1001","name":"Desk"}],"listener":"connected","server_time":"t"}',
    );
    expect(hello).toMatchObject({ type: "hello", extensions: [{ id: "e1", number: "1001" }] });
    const ev = parseStreamEvent(JSON.stringify(ringing));
    expect(ev).toEqual(ringing);
  });

  it("rejects garbage", () => {
    expect(parseStreamEvent("not json")).toBeNull();
    expect(parseStreamEvent('{"type":"surprise"}')).toBeNull();
    expect(parseStreamEvent("[]")).toBeNull();
  });
});
