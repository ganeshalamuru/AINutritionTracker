import { createContext, useContext, useEffect, useState } from "react";
import client, { setAccessToken, setOnAuthFailure } from "../api/client";

// Authenticated-user state. The access token lives in memory inside api/client (not here); the
// refresh token is an HttpOnly cookie the browser holds and replays to /api/auth (invisible to
// JS). On boot we try to exchange that cookie for a fresh access token and reload the user, so a
// page refresh keeps the session without re-login.
const AuthContext = createContext(null);

// Legacy cleanup: earlier builds kept the refresh token in localStorage. It's now a cookie, so
// purge the stale key once (it's dead weight and we never read it again).
localStorage.removeItem("nutriai_refresh");

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  // `loading` covers the initial refresh-on-boot so routes don't flash the login screen
  // before we know whether there's a valid session.
  const [loading, setLoading] = useState(true);

  const applyAuth = (u, accessToken) => {
    setAccessToken(accessToken);
    localStorage.setItem("nutriai_uid", u.id);
    setUser(u);
  };

  const clearAuth = () => {
    setAccessToken(null);
    localStorage.removeItem("nutriai_uid");
    setUser(null);
  };

  // When a transparent refresh fails (session truly gone), client.js calls this; dropping the
  // user re-renders ProtectedRoute, which redirects to /login.
  useEffect(() => {
    setOnAuthFailure(clearAuth);
  }, []);

  // Boot: try to re-establish the session from the refresh cookie. We can't see the cookie from
  // JS, so we just attempt the refresh — a 401 (no/expired cookie) simply means "not logged in".
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await client.post("/auth/refresh");
        setAccessToken(data.access_token);
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
    applyAuth(data.user, data.access_token);
    return data.user;
  };

  const register = async (payload) => {
    const { data } = await client.post("/auth/register", payload);
    applyAuth(data.user, data.access_token);
    return data.user;
  };

  const logout = async () => {
    try {
      await client.post("/auth/logout"); // backend reads + clears the refresh cookie
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
