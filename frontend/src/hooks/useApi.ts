/**
 * useApi.ts — Generic data fetching hook with loading/error states
 *
 * Pattern: SWR-lite. Fetches on mount, provides loading/error/data.
 * For production: replace with react-query or SWR for caching + revalidation.
 */

import { useState, useEffect, useCallback, useRef } from 'react';

interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function useApi<T>(
  fetcher: (() => Promise<T>) | null,
  deps: any[] = [],
) {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: !!fetcher,
    error: null,
  });
  const mountedRef = useRef(true);

  const fetch = useCallback(async () => {
    if (!fetcher) return;
    setState(s => ({ ...s, loading: true, error: null }));
    try {
      const data = await fetcher();
      if (mountedRef.current) setState({ data, loading: false, error: null });
    } catch (err: any) {
      if (mountedRef.current)
        setState({ data: null, loading: false, error: err.message });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetcher, ...deps]);

  useEffect(() => {
    mountedRef.current = true;
    fetch();
    return () => { mountedRef.current = false; };
  }, [fetch]);

  return { ...state, refetch: fetch };
}
