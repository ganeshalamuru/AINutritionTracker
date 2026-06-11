import axios from "axios";

const client = axios.create({ baseURL: "/api" });

client.interceptors.request.use((config) => {
  const profile = JSON.parse(localStorage.getItem("activeProfile") || "null");
  if (profile?.id) config.headers["X-Profile-Id"] = profile.id;
  return config;
});

export default client;
