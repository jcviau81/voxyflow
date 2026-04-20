/**
 * authClient — lazy bearer-token bootstrap + `authFetch` wrapper.
 *
 * Voxyflow gates destructive / secret-writing endpoints with a bearer token.
 * The token is minted server-side (`~/.voxyflow/auth_token`, 0600) and served
 * to the same-origin frontend via `GET /api/auth/bootstrap`. CORS blocks
 * cross-origin pages from reading it.
 *
 * Usage:
 *   await authFetch('/api/settings', { method: 'PUT', body: JSON.stringify(...) })
 *
 * The token is cached in-memory after the first bootstrap call. On a 401 we
 * clear the cache and retry once — that handles the case where the token
 * file was rotated while the tab was open.
 */
let _tokenPromise: Promise<string> | null = null;

async function _bootstrap(): Promise<string> {
  const res = await fetch('/api/auth/bootstrap', { method: 'GET' });
  if (!res.ok) {
    throw new Error(`auth bootstrap failed: ${res.status}`);
  }
  const data = await res.json();
  if (!data?.token) {
    throw new Error('auth bootstrap: missing token in response');
  }
  return data.token as string;
}

function _getToken(): Promise<string> {
  if (_tokenPromise === null) {
    _tokenPromise = _bootstrap().catch((err) => {
      _tokenPromise = null;
      throw err;
    });
  }
  return _tokenPromise;
}

/** Force re-fetch of the token on the next request (e.g. after a 401). */
export function clearAuthToken(): void {
  _tokenPromise = null;
}

/** Warm the cache — safe to call on app boot. */
export function primeAuthToken(): void {
  void _getToken().catch(() => {
    /* will retry on first authFetch */
  });
}

/**
 * Wrapper around `fetch` that injects `Authorization: Bearer <token>`.
 * Retries once on a 401 after clearing the cached token.
 */
export async function authFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const token = await _getToken();
  const headers = new Headers(init.headers || {});
  if (!headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const firstTry = await fetch(input, { ...init, headers });
  if (firstTry.status !== 401) {
    return firstTry;
  }
  clearAuthToken();
  const retryToken = await _getToken();
  const retryHeaders = new Headers(init.headers || {});
  retryHeaders.set('Authorization', `Bearer ${retryToken}`);
  return fetch(input, { ...init, headers: retryHeaders });
}
