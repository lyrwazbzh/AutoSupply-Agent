"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  AuthUser,
  clearAccessToken,
  login as loginRequest,
  logout as logoutRequest,
  refreshSession,
  subscribeSession,
} from "@/lib/auth";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const unsubscribe = subscribeSession(setUser);
    refreshSession()
      .then((payload) => setUser(payload.user))
      .catch(() => {
        clearAccessToken();
        setUser(null);
      })
      .finally(() => setLoading(false));
    return unsubscribe;
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      login: async (username, password) => {
        const payload = await loginRequest(username, password);
        setUser(payload.user);
      },
      logout: async () => {
        await logoutRequest();
        setUser(null);
      },
      hasPermission: (permission) => Boolean(user?.permissions.includes(permission)),
    }),
    [user, loading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
