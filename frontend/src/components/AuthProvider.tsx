import { createContext, createSignal, useContext, onMount, type ParentProps, type Component } from "solid-js";
import { api } from "../api/client";
import type { AuthUser } from "../types";

interface AuthContextValue {
  user: () => AuthUser | null;
  loading: () => boolean;
  login: (username: string, password: string, remember?: boolean) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  isAdmin: () => boolean;
}

const AuthContext = createContext<AuthContextValue>();

export const AuthProvider: Component<ParentProps> = (props) => {
  const [user, setUser] = createSignal<AuthUser | null>(null);
  const [loading, setLoading] = createSignal(true);

  const refreshUser = async () => {
    try {
      const me = await api.getMe();
      setUser(me);
    } catch {
      setUser(null);
    }
  };

  const login = async (username: string, password: string, remember?: boolean) => {
    await api.login(username, password, remember ?? false);
    await refreshUser();
  };

  const logout = async () => {
    await api.logout();
    setUser(null);
  };

  const isAdmin = () => user()?.role === "admin";

  onMount(async () => {
    await refreshUser();
    setLoading(false);
  });

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshUser, isAdmin }}>
      {props.children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
