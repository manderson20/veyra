// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { challengeOf, needsInteraction, newVerifier, parseRedirect, startUrl } from "./sso";

describe("companion single sign-on", () => {
  it("makes a PKCE pair (S256, RFC 7636)", async () => {
    const v0 = "a-fixed-verifier-of-sufficient-length-0123456789";
    // base64url(SHA-256(v0)), computed with Python's hashlib.
    expect(await challengeOf(v0)).toBe("X8YAW1dfU4akjDnfgJp_KFi1PJ3j4I4PUWvon1c8t-k");
    const v = newVerifier();
    expect(v.length).toBeGreaterThanOrEqual(43);
    expect(v).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it("builds the start address", () => {
    const url = new URL(startUrl("https://pbx.example.org", "p1", "https://abc.chromiumapp.org/sso", "ch", true));
    expect(url.pathname).toBe("/api/v1/auth/sso/p1/start");
    expect(url.searchParams.get("client")).toBe("companion");
    expect(url.searchParams.get("redirect_uri")).toBe("https://abc.chromiumapp.org/sso");
    expect(url.searchParams.get("silent")).toBe("true");
  });

  it("reads the code or the error from the redirect", () => {
    const prefix = "https://abc.chromiumapp.org/sso";
    expect(parseRedirect(`${prefix}?code=xyz`, prefix)).toEqual({ code: "xyz" });
    expect(parseRedirect(`${prefix}?error=interaction_required&message=m`, prefix)).toEqual({ error: "interaction_required", message: "m" });
    expect(parseRedirect("https://evil.example/?code=x", prefix)).toMatchObject({ error: "bad_redirect" });
    expect(needsInteraction("interaction_required")).toBe(true);
    expect(needsInteraction("domain_not_allowed")).toBe(false);
  });
});
