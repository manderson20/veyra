# 0011: Password reset by administrator- and console-issued one-time links

**Status:** Accepted (2026-10-12)

**Context:** Veyra has no email delivery until Milestone 7, and some
installations will never have it (isolated networks). Users forget
passwords and accounts get locked. Milestone 0 let an administrator type a
new password for a user, which means the administrator knows it and it must
be shared over some channel.

**Decision:** Password resets use one-time links. An administrator with
`users.write` creates one from the user's page (`POST
/users/{id}/password-reset-link`), or an operator runs `veyra users
reset-password <email>` on the server. The link opens a public page where
the user chooses their own password. Properties:

* The token is 256 bits of randomness; only its SHA-256 digest is stored
  (`password_reset_tokens`). It is shown to the administrator once.
* Valid for 24 hours (`VEYRA_PASSWORD_RESET_TTL_HOURS`), single use, and a
  new link replaces the previous unused one.
* Using it sets the password, clears any lockout and signs the account out
  everywhere. It does not sign the user in.
* The check and reset endpoints share the sign-in rate limit (API and
  NGINX) and answer with one generic 404 for unknown, expired, used and
  disabled-account tokens.
* The administrator-typed password remains available but is **temporary by
  default**: the user must choose their own at the next sign-in
  (`must_change_password`), during which only the authentication routes
  work.

**Consequences:** Nobody but the user knows the final password. The
console command is the recovery path for a locked-out recovery
administrator; whoever can run it already controls the server, the same
trust boundary as `setup-token`. When email delivery arrives, the
self-service "forgot password" flow reuses the same table and endpoints
and only adds a request endpoint and the message.
