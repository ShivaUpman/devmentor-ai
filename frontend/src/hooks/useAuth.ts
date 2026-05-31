/**
 * useAuth.ts — Authentication state management hook
 *
 * WHY a custom hook and not Context + useReducer?
 *   For this scale, a module-level singleton + hook is simpler.
 *   React Query / Zustand would be used at production scale.
 *   The hook pattern keeps auth logic co-located and easy to test.
 *
 * WHY check for a refresh token on mount?
 *   Access tokens live in memory (cleared on refresh).
 *   Refresh token lives in localStorage. On page load: if refresh token
 *   exists, silently get a new access token and restore the session.
 *   Users stay logged in across tab closes and refreshes.
 */

import { useState, useEffect, useCallback } from 'react';
import { authApi, tokenStore, User } from '../utils/api';

interface AuthState {
  user: User | null;
  loading: boolean;
  error: string | null;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    user: null,
    loading: true,
    error: null,
  });

  // On mount: try to restore session from refresh token
  useEffect(() => {
    const restoreSession = async () => {
      const refresh = typeof window !== 'undefined'
        ? localStorage.getItem('refresh_token')
        : null;

      if (!refresh) {
        setState(s => ({ ...s, loading: false }));
        return;
      }

      try {
        // Refresh token exists — silently get a new access token
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/v1/auth/refresh`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refresh }),
          }
        );
        if (!res.ok) throw new Error('Refresh failed');
        const tokens = await res.json();
        tokenStore.set(tokens.access_token);

        const user = await authApi.me();
        setState({ user, loading: false, error: null });
      } catch {
        // Refresh failed — clear stale token, start fresh
        localStorage.removeItem('refresh_token');
        setState({ user: null, loading: false, error: null });
      }
    };

    restoreSession();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setState(s => ({ ...s, loading: true, error: null }));
    try {
      const user = await authApi.login(email, password);
      setState({ user, loading: false, error: null });
      return user;
    } catch (err: any) {
      setState(s => ({ ...s, loading: false, error: err.message }));
      throw err;
    }
  }, []);

  const register = useCallback(async (
    email: string, password: string, full_name: string
  ) => {
    setState(s => ({ ...s, loading: true, error: null }));
    try {
      await authApi.register(email, password, full_name);
      // Auto-login after registration
      return login(email, password);
    } catch (err: any) {
      setState(s => ({ ...s, loading: false, error: err.message }));
      throw err;
    }
  }, [login]);

  const logout = useCallback(async () => {
    await authApi.logout();
    setState({ user: null, loading: false, error: null });
  }, []);

  return {
    user: state.user,
    loading: state.loading,
    error: state.error,
    isAuthenticated: !!state.user,
    login,
    register,
    logout,
  };
}
