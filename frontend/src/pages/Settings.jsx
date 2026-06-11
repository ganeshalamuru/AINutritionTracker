import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useProfile } from "../context/ProfileContext";
import client from "../api/client";
import Toast from "../components/shared/Toast";
import ConfirmModal from "../components/shared/ConfirmModal";

export default function Settings() {
  const { profile, logout } = useProfile();
  const navigate = useNavigate();
  const [apiKey, setApiKey] = useState("");
  const [keySet, setKeySet] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [profiles, setProfiles] = useState([]);
  const [toast, setToast] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);

  useEffect(() => {
    client.get("/config").then((r) => setKeySet(r.data.gemini_api_key_set));
    client.get("/profiles").then((r) => setProfiles(r.data));
  }, []);

  const saveKey = async () => {
    if (!apiKey.trim()) return;
    setSaving(true);
    try {
      await client.put("/config", { gemini_api_key: apiKey.trim() });
      setKeySet(true);
      setApiKey("");
      setToast({ message: "API key saved!", type: "success" });
    } catch {
      setToast({ message: "Failed to save key", type: "error" });
    } finally {
      setSaving(false);
    }
  };

  const deleteProfile = async (id) => {
    await client.delete(`/profiles/${id}`);
    setProfiles((p) => p.filter((x) => x.id !== id));
    if (profile.id === id) { logout(); navigate("/"); }
  };

  return (
    <div className="pt-4 space-y-6 pb-4">
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
      <ConfirmModal
        isOpen={!!confirmDelete}
        message="Delete this profile and all its meals?"
        confirmLabel="Delete"
        onConfirm={() => { const id = confirmDelete; setConfirmDelete(null); deleteProfile(id); }}
        onCancel={() => setConfirmDelete(null)}
      />

      <h2 className="text-xl font-bold text-gray-900">Settings</h2>

      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4 space-y-3">
        <h3 className="font-semibold text-gray-800">Gemini API Key</h3>
        <p className="text-xs text-gray-500">
          Required for AI meal analysis.{" "}
          <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="text-green-600 underline">
            Get a free key here
          </a>
        </p>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-1 rounded-full font-medium ${keySet ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}>
            {keySet ? "Key saved" : "Not set"}
          </span>
        </div>
        <input
          type="password"
          className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400 font-mono"
          placeholder="AIza..."
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
        <button
          onClick={saveKey}
          disabled={saving || !apiKey.trim()}
          className="w-full py-2.5 bg-green-500 text-white rounded-xl text-sm font-medium hover:bg-green-600 disabled:opacity-50"
        >
          {saving ? "Saving..." : keySet ? "Update Key" : "Save Key"}
        </button>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4 space-y-3">
        <h3 className="font-semibold text-gray-800">Profiles</h3>
        {profiles.map((p) => (
          <div key={p.id} className="flex items-center gap-3">
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center text-white font-bold text-sm flex-shrink-0"
              style={{ backgroundColor: p.avatar_color }}
            >
              {p.name.charAt(0).toUpperCase()}
            </div>
            <span className="flex-1 text-sm text-gray-700 font-medium">
              {p.name} {p.id === profile.id && <span className="text-xs text-green-500">(you)</span>}
            </span>
            <button
              onClick={() => setConfirmDelete(p.id)}
              className="text-xs text-red-400 hover:text-red-500 px-2 py-1"
            >
              Delete
            </button>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4">
        <h3 className="font-semibold text-gray-800 mb-2">Access on Mobile</h3>
        <p className="text-xs text-gray-500 mb-2">
          To open this app on your phone, find your computer's local IP address and open it in your mobile browser.
        </p>
        <div className="bg-gray-50 rounded-xl p-3 font-mono text-xs text-gray-700">
          Run in terminal: <span className="text-green-600 font-semibold">ipconfig</span>
          <br />
          Look for: <span className="text-green-600">IPv4 Address</span>
          <br />
          Then open: <span className="text-green-600">http://&lt;your-ip&gt;:8000</span>
        </div>
      </div>

      <button
        onClick={() => { logout(); navigate("/"); }}
        className="w-full py-3 rounded-2xl border-2 border-gray-200 text-gray-600 text-sm font-medium hover:bg-gray-50"
      >
        Switch Profile
      </button>
    </div>
  );
}
