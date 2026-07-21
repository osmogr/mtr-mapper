import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";

export function useAuth() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);

  const refresh = useCallback(async () => {
    try {
      const status = await api.session();
      setAuthenticated(status.authenticated);
    } catch {
      setAuthenticated(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = useCallback(async (password: string) => {
    const status = await api.login(password);
    setAuthenticated(status.authenticated);
    return status.authenticated;
  }, []);

  const logout = useCallback(async () => {
    await api.logout();
    setAuthenticated(false);
  }, []);

  return { authenticated, login, logout, refresh };
}
