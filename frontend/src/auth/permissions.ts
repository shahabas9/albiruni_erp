import type { AuthUser } from "../api/client";

/** Mirrors the backend's SUPER_ADMIN_PERMISSION wildcard convention
 * (app/core/deps.py) — purely for hiding/showing UI; the API re-checks
 * every permission itself regardless of what the client renders. */
export function hasPermission(user: AuthUser | null, permission: string): boolean {
  if (!user) return false;
  return user.permissions.includes("*") || user.permissions.includes(permission);
}
