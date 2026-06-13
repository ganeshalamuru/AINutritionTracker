import axios from "axios";

// 45s timeout so the UI fails gracefully instead of hanging if the backend stalls.
// /analyze runs Stage 1 (vision, ~15s cap) then Stage 2 (several USDA lookups, each up
// to ~10s with a retry), so a slow-but-successful analyze can legitimately take longer
// than 25s; 45s accommodates that while still eventually giving up.
const client = axios.create({ baseURL: "/api", timeout: 45000 });

client.interceptors.request.use((config) => {
  const profile = JSON.parse(localStorage.getItem("activeProfile") || "null");
  if (profile?.id) config.headers["X-Profile-Id"] = profile.id;
  return config;
});

export default client;
