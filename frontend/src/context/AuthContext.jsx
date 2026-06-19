import { createContext, useContext, useEffect, useState } from "react";
import client, {
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
  setOnAuthFailure,
} from "../api/client";

// Authenticated-user state. The access token lives in memory inside api/client (not here),
// the refresh token in localStorage; on boot we exchange the refresh token for a fresh
// access token and reload the user, so a page refresh keeps the session without re-login.
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  // `loading` covers the initial refresh-on-boot so routes don't flash the login screen
  // before we know whether there's a valid session.
  const [loading, setLoading] = useState(true);

  const persistTokens = (tokens) => {
    if (!tokens) return;
    setAccessToken(tokens.access_token);
    setRefreshToken(tokens.refresh_token);
  };

  const applyAuth = (u, tokens) => {
    persistTokens(tokens);
    localStorage.setItem("nutriai_uid", u.id);
    setUser(u);
  };

  const clearAuth = () => {
    setAccessToken(null);
    setRefreshToken(null);
    localStorage.removeItem("nutriai_uid");
    setUser(null);
  };

  // When a transparent refresh fails (session truly gone), client.js calls this; dropping the
  // user re-renders ProtectedRoute, which redirects to /login.
  useEffect(() => {
    setOnAuthFailure(clearAuth);
  }, []);

  // Boot: re-establish the session from the stored refresh token, if any.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getRefreshToken()) {
        setLoading(false);
        return;
      }
      try {
        const { data } = await client.post("/auth/refresh", {
          refresh_token: getRefreshToken(),
        });
        persistTokens(data);
        const me = await client.get("/auth/me");
        if (!cancelled) {
          localStorage.setItem("nutriai_uid", me.data.id);
          setUser(me.data);
        }
      } catch {
        if (!cancelled) clearAuth();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = async (username, password) => {
    const { data } = await client.post("/auth/login", { username, password });
    applyAuth(data.user, data.tokens);
    return data.user;
  };

  const register = async (payload) => {
    const { data } = await client.post("/auth/register", payload);
    applyAuth(data.user, data.tokens);
    return data.user;
  };

  const logout = async () => {
    const rt = getRefreshToken();
    try {
      if (rt) await client.post("/auth/logout", { refresh_token: rt });
    } catch {
      // best-effort revoke; clear locally regardless
    }
    clearAuth();
  };

  // Merge a partial update into the active user (e.g. calorie_goal) so the UI reflects it
  // without a re-fetch. Not persisted to storage — the user is rebuilt from /auth/me on boot.
  const updateUser = (patch) => setUser((u) => (u ? { ...u, ...patch } : u));

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, updateUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
