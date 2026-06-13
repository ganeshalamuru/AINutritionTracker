import axios from "axios";

// 45s default timeout so the UI fails gracefully instead of hanging if the backend stalls.
// This suits cloud requests (vision ~15s cap + a few USDA lookups). The /analyze call with
// a LOCAL Ollama model can run much longer (vision up to ~120s — see OLLAMA_TIMEOUT), so it
// overrides this with a longer per-request timeout in LogMeal.jsx.
const client = axios.create({ baseURL: "/api", timeout: 45000 });

client.interceptors.request.use((config) => {
  const profile = JSON.parse(localStorage.getItem("activeProfile") || "null");
  if (profile?.id) config.headers["X-Profile-Id"] = profile.id;
  return config;
});

export default client;
