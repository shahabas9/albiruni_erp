import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type Page } from "../api/client";

export const PAGE_SIZE = 50;

/**
 * One page of a server-side list. `key` is every filter the fetch depends on
 * (as a string); changing it goes back to the first page. `version` (from
 * AppData) refetches the current page after any shared refresh.
 */
export function usePaged<T>(
  fetchPage: (limit: number, offset: number) => Promise<Page<T>>,
  key: string,
  version: number,
  enabled = true,
) {
  const [page, setPage] = useState(0);
  const [data, setData] = useState<Page<T>>({ rows: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchRef = useRef(fetchPage);
  fetchRef.current = fetchPage;
  const lastKey = useRef(key);
  const latest = useRef(0); // ignore responses to requests that were superseded

  // A new filter starts from the first page.
  if (lastKey.current !== key) {
    lastKey.current = key;
    if (page !== 0) setPage(0);
  }

  const load = useCallback(async () => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const id = ++latest.current;
    setLoading(true);
    try {
      const result = await fetchRef.current(PAGE_SIZE, page * PAGE_SIZE);
      if (id !== latest.current) return;
      setData(result);
      setError(null);
    } catch (err) {
      if (id !== latest.current) return;
      setError(err instanceof ApiError ? err.message : "Couldn't reach the Albiruni API.");
    } finally {
      if (id === latest.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, page, version, enabled]);

  useEffect(() => {
    void load();
  }, [load]);

  return { ...data, page, setPage, loading, error, reload: load };
}
