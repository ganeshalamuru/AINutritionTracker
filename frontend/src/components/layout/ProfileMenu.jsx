import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProfile } from "../../context/ProfileContext";
import client from "../../api/client";
import PinPad from "../profile/PinPad";

// Avatar button in the TopBar. Opens a dropdown to switch profiles (PIN-verified inline)
// or log out — replacing the old "click avatar = instant logout" behavior.
export default function ProfileMenu() {
  const { profile, login, logout } = useProfile();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [profiles, setProfiles] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [switchTarget, setSwitchTarget] = useState(null);
  const [pinError, setPinError] = useState("");

  // Lazy-load the profile list the first time the menu opens (TopBar remounts per route,
  // so fetching on mount would re-request on every navigation).
  const toggleMenu = () => {
    const next = !open;
    setOpen(next);
    if (next && !loaded) {
      client.get("/profiles").then((r) => { setProfiles(r.data); setLoaded(true); });
    }
  };

  const others = profiles.filter((p) => p.id !== profile?.id);

  const handleLogout = () => {
    setOpen(false);
    logout();
    navigate("/");
  };

  const startSwitch = (p) => {
    setOpen(false);
    setPinError("");
    setSwitchTarget(p);
  };

  const handlePinSubmit = async (pin) => {
    setPinError("");
    try {
      const { data } = await client.post("/profiles/verify", { profile_id: switchTarget.id, pin });
      login(data);
      setSwitchTarget(null);
      navigate("/home");
    } catch {
      setPinError("Wrong PIN, try again");
    }
  };

  return (
    <>
      <div className="relative">
        <button
          onClick={toggleMenu}
          className="w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-bold"
          style={{ backgroundColor: profile?.avatar_color || "#22c55e" }}
          title="Switch profile"
          aria-label="Profile menu"
        >
          {profile?.name?.charAt(0).toUpperCase()}
        </button>

        {open && (
          <>
            {/* transparent backdrop closes the menu on outside click */}
            <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} aria-hidden="true" />
            <div className="absolute right-0 mt-2 w-56 bg-white rounded-2xl shadow-xl border border-gray-100 z-30 overflow-hidden">
              <p className="px-4 pt-3 pb-1 text-xs font-semibold text-gray-400 uppercase tracking-wide">
                Switch profile
              </p>
              {others.length > 0 ? (
                others.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => startSwitch(p)}
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 text-left"
                  >
                    <div
                      className="w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-bold flex-shrink-0"
                      style={{ backgroundColor: p.avatar_color }}
                    >
                      {p.name.charAt(0).toUpperCase()}
                    </div>
                    <span className="text-sm font-medium text-gray-700 truncate">{p.name}</span>
                  </button>
                ))
              ) : (
                <p className="px-4 py-2.5 text-sm text-gray-400">
                  {loaded ? "No other profiles" : "Loading..."}
                </p>
              )}
              <div className="border-t border-gray-100 my-1" />
              <button
                onClick={handleLogout}
                className="w-full px-4 py-2.5 text-left text-sm font-medium text-red-500 hover:bg-red-50"
              >
                Log out
              </button>
            </div>
          </>
        )}
      </div>

      {switchTarget && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 px-4"
          onClick={() => { setSwitchTarget(null); setPinError(""); }}
        >
          <div
            className="bg-white rounded-3xl shadow-xl w-full max-w-sm p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex flex-col items-center mb-4">
              <div
                className="w-16 h-16 rounded-full flex items-center justify-center text-white text-2xl font-bold mb-2"
                style={{ backgroundColor: switchTarget.avatar_color }}
              >
                {switchTarget.name.charAt(0).toUpperCase()}
              </div>
              <h2 className="text-lg font-semibold text-gray-800">{switchTarget.name}</h2>
              <p className="text-sm text-gray-500">Enter PIN to switch</p>
            </div>
            <PinPad
              onSubmit={handlePinSubmit}
              onCancel={() => { setSwitchTarget(null); setPinError(""); }}
              error={pinError}
            />
          </div>
        </div>
      )}
    </>
  );
}
