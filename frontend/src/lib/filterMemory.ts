import type { ViewFilters, ViewPage } from "../api/client";

// Per-browser memory of each list's last filters, so a page opens the way you left it.
// Storage can be unavailable (private mode, blocked site data): then we simply don't remember.
const key = (page: ViewPage) => `albiruni.filters.${page}`;

export function recallFilters(page: ViewPage): ViewFilters {
  try {
    const raw = localStorage.getItem(key(page));
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? (parsed as ViewFilters) : {};
  } catch {
    return {};
  }
}

export function rememberFilters(page: ViewPage, filters: ViewFilters): void {
  try {
    localStorage.setItem(key(page), JSON.stringify(filters));
  } catch {
    // not remembered this time
  }
}

/** A filter value from the URL (links from alerts, Ask ERP, the dashboard) wins over the remembered one. */
export function initialFilter<T extends string>(urlValue: string | null, page: ViewPage, name: string, fallback: T): T {
  if (urlValue !== null) return urlValue as T;
  const remembered = recallFilters(page)[name];
  return typeof remembered === "string" ? (remembered as T) : fallback;
}
