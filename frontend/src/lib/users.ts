import type { User } from "./types";

/** True while an account lockout (after repeated failed sign-ins) is in force. */
export function isLockedOut(user: Pick<User, "locked_until">, now: Date = new Date()): boolean {
  if (!user.locked_until) return false;
  const until = new Date(user.locked_until).getTime();
  return !Number.isNaN(until) && until > now.getTime();
}
