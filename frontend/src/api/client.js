import axios from "axios";

// 45s default timeout so the UI fails gracefully instead of hanging if the backend stalls.
// This suits cloud requests (vision ~15s cap + a few USDA lookups). The /analyze call with
// a LOCAL Ollama model can run much longer (vision up to ~120s — see OLLAMA_TIMEOUT), so it
// overrides this with a longer per-request timeout in LogMeal.jsx.
// withCredentials so the browser sends/stores the HttpOnly refresh cookie (set by the backend
// on login/refresh, scoped to /api/auth); same-origin serving means this is a no-op in normal
// use but is required if the API is ever reached cross-origin (CORS_ORIGINS).
const client = axios.create({ baseURL: "/api", timeout: 45000, withCredentials: true });

// --- Auth token plumbing -------------------------------------------------
// The access token lives in memory only (set by AuthContext) to limit XSS exposure. The refresh
// token is NOT handled here at all — it's an HttpOnly cookie the browser stores and replays to
// /api/auth, invisible to JavaScript. On a 401 we transparently refresh once (single-flight, the
// cookie rides along) and retry; if that fails we hand off to the registered logout handler so
// the app drops to the login screen.
let accessToken = null;
let onAuthFailure = () => {};

export const setAccessToken = (t) => {
  accessToken = t || null;
};
export const setOnAuthFailure = (fn) => {
  onAuthFailure = fn || (() => {});
};

// A bare instance for the refresh call so it never recurses through the interceptors below.
const bare = axios.create({ baseURL: "/api", timeout: 45000, withCredentials: true });

client.interceptors.request.use((config) => {
  if (accessToken) config.headers["Authorization"] = `Bearer ${accessToken}`;
  // X-User-Id is used only for backend log correlation (not trust); send the user id when known.
  const uid = localStorage.getItem("nutriai_uid");
  if (uid) config.headers["X-User-Id"] = uid;
  return config;
});

let refreshPromise = null;

async function refreshAccessToken() {
  // No body: the refresh token is sent automatically as the HttpOnly cookie. A 401 here (no/expired
  // cookie) rejects, which the interceptor below turns into a logout.
  const { data } = await bare.post("/auth/refresh");
  setAccessToken(data.access_token);
  return data.access_token;
}

client.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    const original = error.config;
    const status = error.response?.status;
    // Don't try to refresh for auth endpoints themselves (a 401 there is a real credential
    // failure, not an expired access token), and only retry an original request once.
    const isAuthCall = original?.url?.includes("/auth/");
    if (status === 401 && original && !original._retried && !isAuthCall) {
      original._retried = true;
      try {
        refreshPromise = refreshPromise || refreshAccessToken();
        const newToken = await refreshPromise;
        refreshPromise = null;
        original.headers["Authorization"] = `Bearer ${newToken}`;
        return client(original);
      } catch (e) {
        refreshPromise = null;
        setAccessToken(null);
        onAuthFailure();
        return Promise.reject(error);
      }
    }
    return Promise.reject(error);
  }
);

export default client;
