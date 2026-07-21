import type { ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";

import { useAuth } from "../../hooks/useAuth";

export default function RequireAuth({ children }: { children: ReactNode }) {
  const { authenticated, logout } = useAuth();

  if (authenticated === null) return <p className="admin-loading">Checking session…</p>;
  if (!authenticated) return <Navigate to="/admin/login" replace />;

  return (
    <div className="admin-page">
      <nav className="admin-nav">
        <Link to="/">&larr; map</Link>
        <Link to="/admin/targets">Targets</Link>
        <Link to="/admin/target-lists">Target lists</Link>
        <button onClick={() => logout()} className="admin-logout">
          Log out
        </button>
      </nav>
      {children}
    </div>
  );
}
