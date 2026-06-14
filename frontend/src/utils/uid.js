// Lightweight client-side unique id. Uses Math.random (NOT crypto.randomUUID, which is
// unavailable in some of the browsers this app runs on).
export const uid = () =>
  Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
