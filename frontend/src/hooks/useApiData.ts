// SPDX-License-Identifier: AGPL-3.0-or-later
"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ApiOptions } from "@/lib/api";

export interface ApiData<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
  setData: (value: T | undefined) => void;
}

interface Result<T> {
  key: string;
  data: T | undefined;
  error: unknown;
}

/** GET `path` (null = skip) and track loading/error state. Re-fetches when the query changes. */
export function useApiData<T>(path: string | null, query?: ApiOptions["query"]): ApiData<T> {
  const [nonce, setNonce] = useState(0);
  const queryKey = JSON.stringify(query ?? {});
  const key = path === null ? "" : `${path}?${queryKey}#${nonce}`;
  // Keep the previous data while reloading so pages do not flash empty.
  const [result, setResult] = useState<Result<T>>({ key: "", data: undefined, error: null });

  useEffect(() => {
    if (path === null) return;
    const ctrl = new AbortController();
    api
      .get<T>(path, JSON.parse(queryKey) as ApiOptions["query"], { signal: ctrl.signal })
      .then((data) => setResult({ key, data, error: null }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setResult((r) => ({ key, data: r.data, error }));
      });
    return () => ctrl.abort();
  }, [path, queryKey, key]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const setData = useCallback((data: T | undefined) => setResult((r) => ({ ...r, data, error: null })), []);
  const current = result.key === key;
  return {
    data: path === null ? undefined : result.data,
    error: current ? result.error : null,
    loading: path !== null && !current,
    reload,
    setData,
  };
}
