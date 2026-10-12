import { describe, expect, it } from "vitest";
import { describeUserAgent } from "./useragent";

describe("describeUserAgent", () => {
  it("names common browsers and platforms", () => {
    expect(describeUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36").label).toBe("Chrome on Windows");
    expect(describeUserAgent("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36 Edg/130.0").label).toBe("Microsoft Edge on Windows");
    expect(describeUserAgent("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15").label).toBe("Safari on macOS");
    expect(describeUserAgent("Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0").label).toBe("Firefox on Linux");
    expect(describeUserAgent("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1").label).toBe("Safari on iPhone");
  });

  it("falls back honestly", () => {
    expect(describeUserAgent(null).label).toBe("Unknown device");
    expect(describeUserAgent("curl/8.5.0").label).toBe("curl");
    expect(describeUserAgent("SomethingElse/1.0")).toEqual({ browser: null, platform: null, label: "Unknown device" });
  });
});
