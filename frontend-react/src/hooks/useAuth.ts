/**
 * useAuth — authentication hook for Voxyflow.
 *
 * The current backend has no JWT/login flow — it is a local tool accessed
 * directly. This hook provides the auth interface expected by ProtectedRoute
 * and API hooks, defaulting to always-authenticated.
 *
 * When a real auth layer is added to the backend, implement token storage and
 * refresh logic here without changing callers.
 */
import { useCallback } from 'react';
import { useTabStore } from '../stores/useTabStore';

const TOKEN_KEY = 'voxyflow_auth_token';

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export interface UseAuthReturn {
  /** True when the user is allowed to access protected routes. */
  isAuthenticated: boolean;
  /** Store a new auth token (e.g. after login). */
  setToken: (token: string) => void;
  /** Clear credentials and log out. */
  logout: () => void;
}

export function useAuth(): UseAuthReturn {
  // The app is a local tool — no server-side auth required.
  // isAuthenticated is always true; token helpers are no-ops until a real
  // auth layer is introduced.
  const isAuthenticated = true;

  const setToken = useCallback((token: string) => {
    setStoredToken(token);
  }, []);

  const logout = useCallback(() => {
    clearStoredToken();
    // Future: redirect to /login and reset stores.
  }, []);

  return { isAuthenticated, setToken, logout };
}

// Re-export store selector for convenience — components that only need the
// active tab do not have to import two hooks.
export { useTabStore };
