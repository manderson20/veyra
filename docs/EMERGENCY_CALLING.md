# Emergency Calling (Design Notes)

**Emergency calling is safety-critical. It is not implemented and must not
be relied on.** Production emergency calling stays disabled until
configuration and testing are complete (planned validation: Milestone 17).
Organizations deploying Veyra are responsible for complying with the
regulations that apply to them. These notes are not legal advice.

## U.S. regulatory requirements for multi-line telephone systems (MLTS)

* **Kari's Law** (47 U.S.C. § 623; FCC rules at 47 CFR § 9.16): users must be able to dial 911 **directly**, without a prefix such as "9". The system must send a **notification** to a central location on site (for example a front desk or security office) when 911 is dialed, where someone is likely to see it. This applies to systems manufactured, imported, sold or installed after February 16, 2020.
* **RAY BAUM'S Act, Section 506** (FCC rules at 47 CFR § 9.16): 911 calls from an MLTS must convey a **dispatchable location**, meaning a validated street address plus details such as floor or room. Compliance dates were January 6, 2021 for fixed devices and January 6, 2022 for non-fixed devices.
* State laws may add requirements. Other countries have their own rules (for example 112 and 999).

## Design requirements for Veyra

* Emergency numbers (911, and others as configured) are dialable from every extension without a prefix and are matched before any other outbound route. Configuration validation fails if any outbound route could block them.
* **Site-specific routing:** a call goes out through the trunk serving the caller's site, with that site's emergency caller ID (ELIN or DID) and the location registered with the carrier's E911 service.
* **Dispatchable location:** sites, buildings and (later) rooms hold civic address data. The `sites` table already has address fields. Devices map to locations, and non-fixed and remote users need location updates.
* **Callback:** the PSAP's callback to the emergency caller ID must ring the calling extension, or a designated responder, for a configurable period.
* **On-site notification:** configurable recipients (paging group, desk phone, email or SMS through an integration), including the caller's extension, name and location.
* **Failover:** if the primary trunk is down, try a secondary emergency path. HA failover must preserve emergency routing.
* **Testing:** carrier-coordinated test calls (for example 933 where the carrier supports it) as part of activation, with results recorded.
* **Visibility:** the dashboard shows the readiness of emergency calling per site. It stays "Not configured" until the requirements above are met.

Paging integration (for example Algo SIP speakers) is not a substitute for a
life-safety mass notification system.

## Status after Milestone 6 (routing only)

Implemented ([TRUNKS_ROUTING.md](TRUNKS_ROUTING.md) §7): outbound routes
marked *emergency* are evaluated before every other route, so `911` (and
`933`) dial directly from any extension without a prefix; the numbering plan
reserves both; an emergency route uses its own caller ID (the ELIN or the
registered DID), a 120-second dial timeout, ignores trunk channel caps and
the loop check, and logs each call at WARNING level in the Asterisk log; the
Outbound Routes page warns when no enabled emergency route exists.

Not implemented: on-site notification (Kari's Law), per-site trunk selection
and dispatchable location (RAY BAUM'S Act), callback handling, carrier test
records and the readiness dashboard (Milestone 17). **Emergency calling is
still not certified and must not be relied on.**
