import { createContext, useContext, useState } from "react";

export const GUEST_PROFILE = { id: 0, name: "Guest", avatar_color: "#9ca3af", isGuest: true };

const ProfileContext = createContext(null);

export function ProfileProvider({ children }) {
  const [profile, setProfile] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("activeProfile")) || null;
    } catch {
      return null;
    }
  });

  const login = (p) => {
    setProfile(p);
    localStorage.setItem("activeProfile", JSON.stringify(p));
  };

  const logout = () => {
    setProfile(null);
    localStorage.removeItem("activeProfile");
  };

  return (
    <ProfileContext.Provider value={{ profile, login, logout }}>
      {children}
    </ProfileContext.Provider>
  );
}

export function useProfile() {
  return useContext(ProfileContext);
}
