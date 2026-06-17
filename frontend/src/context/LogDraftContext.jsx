import { createContext, useContext, useEffect, useState } from "react";
import { useProfile } from "./ProfileContext";

// Holds the in-progress meal-log draft (staged photos + their per-photo analysis, draft
// edits and hints) above the router, so it survives navigating away from /log and back —
// LogMeal unmounts on a tab switch, and component-local state would be lost. State is kept
// in memory only (photos are File/blob objects), so a full page refresh still starts fresh.
const LogDraftContext = createContext(null);

export function LogDraftProvider({ children }) {
  const { profile } = useProfile();
  const [photos, setPhotos] = useState([]);

  // Clear the draft when the active profile changes or logs out — a half-finished log
  // belongs to whoever staged it, not the next profile.
  const profileId = profile?.id ?? null;
  useEffect(() => {
    setPhotos([]);
  }, [profileId]);

  return (
    <LogDraftContext.Provider value={{ photos, setPhotos }}>
      {children}
    </LogDraftContext.Provider>
  );
}

export function useLogDraft() {
  return useContext(LogDraftContext);
}
