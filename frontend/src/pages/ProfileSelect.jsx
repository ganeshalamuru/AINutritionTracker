import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useProfile, GUEST_PROFILE } from "../context/ProfileContext";
import PinPad from "../components/profile/PinPad";
import client from "../api/client";

export default function ProfileSelect() {
  const [profiles, setProfiles] = useState([]);
  const [selected, setSelected] = useState(null);
  const [pinError, setPinError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newPin, setNewPin] = useState("");
  const [newColor, setNewColor] = useState("#22c55e");
  const [creating, setCreating] = useState(false);
  const { login } = useProfile();
  const navigate = useNavigate();

  const colors = ["#22c55e", "#3b82f6", "#f97316", "#a855f7", "#ec4899", "#ef4444"];

  useEffect(() => {
    client.get("/profiles").then((r) => setProfiles(r.data));
  }, []);

  const handlePinSubmit = async (pin) => {
    setPinError("");
    try {
      const { data } = await client.post("/profiles/verify", { pin });
      login(data);
      navigate("/home");
    } catch {
      setPinError("Wrong PIN, try again");
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!newName.trim() || newPin.length !== 4) return;
    setCreating(true);
    try {
      const { data } = await client.post("/profiles", { name: newName.trim(), pin: newPin, avatar_color: newColor });
      login(data);
      navigate("/home");
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to create profile");
    } finally {
      setCreating(false);
    }
  };

  if (selected) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm bg-white rounded-3xl shadow-sm p-6">
          <div className="flex flex-col items-center mb-6">
            <div
              className="w-16 h-16 rounded-full flex items-center justify-center text-white text-2xl font-bold mb-2"
              style={{ backgroundColor: selected.avatar_color }}
            >
              {selected.name.charAt(0).toUpperCase()}
            </div>
            <h2 className="text-lg font-semibold text-gray-800">{selected.name}</h2>
            <p className="text-sm text-gray-500">Enter your PIN</p>
          </div>
          <PinPad
            onSubmit={handlePinSubmit}
            onCancel={() => { setSelected(null); setPinError(""); }}
            error={pinError}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center px-4 py-8">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="text-5xl mb-3">🥗</div>
          <h1 className="text-2xl font-bold text-gray-900">NutriAI</h1>
          <p className="text-sm text-gray-500 mt-1">Who's tracking today?</p>
        </div>

        <div className="space-y-3 mb-4">
          {profiles.map((p) => (
            <button
              key={p.id}
              onClick={() => setSelected(p)}
              className="w-full bg-white rounded-2xl shadow-sm border border-gray-100 p-4 flex items-center gap-3 hover:shadow-md active:scale-98 transition-all text-left"
            >
              <div
                className="w-11 h-11 rounded-full flex items-center justify-center text-white text-lg font-bold flex-shrink-0"
                style={{ backgroundColor: p.avatar_color }}
              >
                {p.name.charAt(0).toUpperCase()}
              </div>
              <span className="font-medium text-gray-800">{p.name}</span>
              <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4 text-gray-400 ml-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          ))}

          <button
            onClick={() => { login(GUEST_PROFILE); navigate("/home"); }}
            className="w-full bg-gray-100 rounded-2xl p-4 flex items-center gap-3 hover:bg-gray-200 transition-all text-left"
          >
            <div className="w-11 h-11 rounded-full bg-gray-300 flex items-center justify-center text-white text-lg font-bold flex-shrink-0">G</div>
            <div>
              <p className="font-medium text-gray-700">Continue as Guest</p>
              <p className="text-xs text-gray-500">Analyze meals without saving</p>
            </div>
          </button>
        </div>

        {!showCreate ? (
          <button
            onClick={() => setShowCreate(true)}
            className="w-full border-2 border-dashed border-green-300 text-green-600 rounded-2xl p-4 text-sm font-medium hover:bg-green-50 transition-colors"
          >
            + Create new profile
          </button>
        ) : (
          <form onSubmit={handleCreate} className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4 space-y-4">
            <h3 className="font-semibold text-gray-800">New Profile</h3>
            <input
              className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400"
              placeholder="Your name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              required
            />
            <div>
              <label className="text-xs text-gray-500 mb-1 block">4-digit PIN</label>
              <input
                className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400 tracking-widest"
                placeholder="e.g. 1234"
                maxLength={4}
                value={newPin}
                onChange={(e) => setNewPin(e.target.value.replace(/\D/g, ""))}
                required
                type="password"
                inputMode="numeric"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-2 block">Avatar color</label>
              <div className="flex gap-2">
                {colors.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setNewColor(c)}
                    className={`w-8 h-8 rounded-full transition-all ${newColor === c ? "ring-2 ring-offset-2 ring-gray-400 scale-110" : ""}`}
                    style={{ backgroundColor: c }}
                  />
                ))}
              </div>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="flex-1 py-2.5 rounded-xl border border-gray-200 text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={creating}
                className="flex-1 py-2.5 rounded-xl bg-green-500 text-white text-sm font-medium hover:bg-green-600 disabled:opacity-50"
              >
                {creating ? "Creating..." : "Create"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
