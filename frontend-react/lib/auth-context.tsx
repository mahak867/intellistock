"use client";

import * as React from "react";
import { login as apiLogin, getMe } from "./api";

interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
}

interface AuthContextValue {
  token: string | null;
  user: User | null;
  loading: boolean;
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = React.useState<string | null>(null);
  const [user, setUser] = React.useState<User | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const stored = window.localStorage.getItem("intellistock_token");
    if (!stored) {
      Promise.resolve().then(() => setLoading(false));
      return;
    }
    // Restore the session only after the server confirms the token, so a stale token never renders the app.
    getMe(stored)
      .then((me) => { setToken(stored); setUser(me); })
      .catch(() => window.localStorage.removeItem("intellistock_token"))
      .finally(() => setLoading(false));
  }, []);

  const signIn = async (email: string, password: string) => {
    setError(null);
    try {
      const res = await apiLogin(email, password);
      window.localStorage.setItem("intellistock_token", res.access_token);
      setToken(res.access_token);
      const me = await getMe(res.access_token);
      setUser(me);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign in failed");
      throw e;
    }
  };

  const signOut = () => {
    window.localStorage.removeItem("intellistock_token");
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ token, user, loading, error, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
