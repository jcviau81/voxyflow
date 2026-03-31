import { Navigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

interface ProtectedRouteProps {
  children: React.ReactNode;
  /** Route to redirect to when not authenticated. Defaults to /login. */
  redirectTo?: string;
}

/**
 * Wraps routes that require authentication.
 * Currently the app is a local tool with no login flow, so isAuthenticated is
 * always true. The wrapper is in place so adding real auth later only requires
 * changes to useAuth, not to every route.
 */
export function ProtectedRoute({ children, redirectTo = '/login' }: ProtectedRouteProps) {
  const { isAuthenticated } = useAuth();

  if (!isAuthenticated) {
    return <Navigate to={redirectTo} replace />;
  }

  return <>{children}</>;
}
