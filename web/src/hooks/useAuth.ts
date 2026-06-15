import { useState, useEffect, useCallback } from "react";
import { apiPost, apiGet } from "@/lib/api";

export interface AuthUser {
  id: string;
  username: string;
  created_at: string;
}

interface AuthState {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
}

interface LoginResponse {
  token: string;
  user: AuthUser;
}

interface MeResponse {
  user: AuthUser;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    user: null,
    token: localStorage.getItem("auth_token"),
    loading: true,
  });

  // On mount, check for stored token and validate it
  useEffect(() => {
    const token = localStorage.getItem("auth_token");
    const storedUser = localStorage.getItem("auth_user");

    if (!token) {
      setState({ user: null, token: null, loading: false });
      return;
    }

    // Try to use cached user first, then validate in background
    if (storedUser) {
      try {
        const user = JSON.parse(storedUser) as AuthUser;
        setState({ user, token, loading: false });
      } catch {
        // Invalid cached user, validate with server
      }
    }

    apiGet<MeResponse>("me")
      .then((data) => {
        localStorage.setItem("auth_user", JSON.stringify(data.user));
        setState({ user: data.user, token, loading: false });
      })
      .catch(() => {
        localStorage.removeItem("auth_token");
        localStorage.removeItem("auth_user");
        setState({ user: null, token: null, loading: false });
      });
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const data = await apiPost<LoginResponse>("login", { username, password });
    localStorage.setItem("auth_token", data.token);
    localStorage.setItem("auth_user", JSON.stringify(data.user));
    setState({ user: data.user, token: data.token, loading: false });
    return data.user;
  }, []);

  const register = useCallback(async (username: string, password: string) => {
    const data = await apiPost<LoginResponse>("register", { username, password });
    localStorage.setItem("auth_token", data.token);
    localStorage.setItem("auth_user", JSON.stringify(data.user));
    setState({ user: data.user, token: data.token, loading: false });
    return data.user;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("auth_user");
    setState({ user: null, token: null, loading: false });
  }, []);

  return {
    user: state.user,
    token: state.token,
    loading: state.loading,
    isAuthenticated: !!state.user,
    login,
    register,
    logout,
  };
}
