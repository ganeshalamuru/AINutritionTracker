import axios from "axios";

// 25s timeout so the UI fails gracefully instead of hanging if the backend stalls
// (the backend caps the model call at ~10s + one retry, so this is a safety net).
const client = axios.create({ baseURL: "/api", timeout: 25000 });

client.interceptors.request.use((config) => {
  const profile = JSON.parse(localStorage.getItem("activeProfile") || "null");
  if (profile?.id) config.headers["X-Profile-Id"] = profile.id;
  return config;
});

export default client;
