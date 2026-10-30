# Custom dialplan

An escape hatch for what Veyra has no feature for (gap analysis §3.5): a
platform administrator's own Asterisk contexts, deployed through the usual
revisions. Owner decision 2026-10-30: strict, platform administrators only.

## 1. Rules

* `GET`/`PUT /telephony/custom-dialplan`: `system.settings.read` / `.write`,
  which are platform-only. Organization administrators cannot use it. The audit
  log keeps the whole text before and after each change.
* Stored in `system_settings` (`telephony.custom_dialplan`), carried in the
  snapshot, and appended to `extensions.conf`. The generator checks it again,
  so text a later release refuses stops the deployment rather than loading.
* Accepted line by line (`veyra/telephony/custom_dialplan.py`): comments,
  `[custom-*]`, `exten =>`, `same =>`, `include => custom-*` for a context in
  the same text. So `#include`, `#exec`, `[globals]`, switches and templates
  never reach the engine. Backslashes and block comments are refused.
* Refused anywhere in a line: the applications and functions in
  `BLOCKED_APPLICATIONS` and `BLOCKED_FUNCTIONS`, and names built from
  variables (`${${A}(x)}`, `Set(${A}(x)=y)`).

## 2. What this does not promise

The list is not a sandbox. Dialplan is code, and an application added by a
future Asterisk could reach something the list does not name. Custom dialplan
can also dial out through a trunk directly, past classes of service and
outbound routes. That is why it is platform-only, audited and reviewed at
deployment like any other change. `Queue` and `Record` are on the list for
their command and file arguments: send calls to a Veyra queue or feature with
`Goto` instead.

## 3. Reaching it

Calls enter through a **Custom** destination. (Being built; until it ships the
contexts load but no call reaches them, except by `Goto` from another custom
context.)
