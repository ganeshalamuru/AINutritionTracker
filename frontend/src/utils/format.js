// Date/time formatting for meal timestamps. The backend stores `logged_at` as a naive
// UTC string (no timezone suffix), so we append "Z" before parsing to render it in the
// user's local time.
export const parseUTC = (ts) => new Date(ts + "Z");

export const formatTime = (ts) =>
  parseUTC(ts).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });

export const formatDateTime = (ts) =>
  parseUTC(ts).toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });

export const formatDateHeading = (ts) =>
  parseUTC(ts).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
