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
  const [groqKey, setGroqKey] = useState("");
  const [groqSet, setGroqSet] = useState(false);
  const [savingGroq, setSavingGroq] = useState(false);
  const [usdaKey, setUsdaKey] = useState("");
  const [usdaSet, setUsdaSet] = useState(false);
  const [savingUsda, setSavingUsda] = useState(false);
  const [provider, setProvider] = useState("groq");
  const [model, setModel] = useState("");
  const [savingModel, setSavingModel] = useState(false);
  const [profiles, setProfiles] = useState([]);
  const [toast, setToast] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);

  // Provider -> its selectable models. The provider dropdown picks the group; the
  // model dropdown lists that group's `models`.
  const PROVIDERS = [
    { id: "groq", label: "Groq (cloud)", models: [
      { model: "meta-llama/llama-4-scout-17b-16e-instruct", label: "Llama 4 Scout — fast, ~1k/day" },
    ]},
    { id: "gemini", label: "Gemini (cloud)", models: [
      { model: "gemini-2.5-flash", label: "2.5 Flash — reliable, ~20/day" },
      { model: "gemma-4-31b-it", label: "Gemma 4 31B — high RPD but low TPM" },
    ]},
    { id: "ollama", label: "Ollama (local)", models: [
      { model: "qwen3-vl:4b-instruct", label: "Qwen3-VL 4B — fast, fits 8 GB GPU" },
      { model: "qwen3-vl:8b-instruct", label: "Qwen3-VL 8B — more accurate, slower on 8 GB" },
    ]},
  ];
  const modelsFor = (p) => (PROVIDERS.find((x) => x.id === p)?.models ?? []);

  useEffect(() => {
    client.get("/config").then((r) => {
      setKeySet(r.data.gemini_api_key_set);
      setGroqSet(r.data.groq_api_key_set);
      setUsdaSet(r.data.usda_api_key_set);
      const p = r.data.vision_provider || "groq";
      setProvider(p);
      setModel(r.data.vision_model || modelsFor(p)[0]?.model || "");
    });
    client.get("/profiles").then((r) => setProfiles(r.data));
  }, []);

  const saveConfig = async (nextProvider, nextModel) => {
    setProvider(nextProvider);
    setModel(nextModel);
    setSavingModel(true);
    try {
      await client.put("/config", { vision_provider: nextProvider, vision_model: nextModel });
      setToast({ message: "Model updated!", type: "success" });
    } catch {
      setToast({ message: "Failed to update model", type: "error" });
    } finally {
      setSavingModel(false);
    }
  };

  // Switching provider picks that provider's first model (the current model usually
  // doesn't belong to the new provider).
  const onProviderChange = (p) => saveConfig(p, modelsFor(p)[0]?.model || "");
  const onModelChange = (m) => saveConfig(provider, m);

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

  const saveGroqKey = async () => {
    if (!groqKey.trim()) return;
    setSavingGroq(true);
    try {
      await client.put("/config", { groq_api_key: groqKey.trim() });
      setGroqSet(true);
      setGroqKey("");
      setToast({ message: "Groq key saved!", type: "success" });
    } catch {
      setToast({ message: "Failed to save key", type: "error" });
    } finally {
      setSavingGroq(false);
    }
  };

  const saveUsdaKey = async () => {
    if (!usdaKey.trim()) return;
    setSavingUsda(true);
    try {
      await client.put("/config", { usda_api_key: usdaKey.trim() });
      setUsdaSet(true);
      setUsdaKey("");
      setToast({ message: "USDA key saved!", type: "success" });
    } catch {
      setToast({ message: "Failed to save key", type: "error" });
    } finally {
      setSavingUsda(false);
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
        <h3 className="font-semibold text-gray-800">AI Vision Model</h3>
        <p className="text-xs text-gray-500">
          Model used to analyze meal photos. Groq · Llama 4 Scout is fastest with the highest free daily limit.
          {provider === "ollama"
            ? " Ollama runs locally — no API key needed; make sure the Ollama app is running and the model is pulled."
            : " The selected provider needs its API key set below."}
        </p>
        <div className="space-y-2">
          <label className="block text-xs font-medium text-gray-600">Provider</label>
          <select
            value={provider}
            onChange={(e) => onProviderChange(e.target.value)}
            disabled={savingModel}
            className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400 bg-white disabled:opacity-50"
          >
            {PROVIDERS.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
          <label className="block text-xs font-medium text-gray-600">Model</label>
          <select
            value={model}
            onChange={(e) => onModelChange(e.target.value)}
            disabled={savingModel}
            className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400 bg-white disabled:opacity-50"
          >
            {modelsFor(provider).map((m) => (
              <option key={m.model} value={m.model}>{m.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4 space-y-3">
        <h3 className="font-semibold text-gray-800">
          Groq API Key {provider === "groq" && <span className="text-xs text-green-500">(active)</span>}
        </h3>
        <p className="text-xs text-gray-500">
          Used by the Groq vision provider.{" "}
          <a href="https://console.groq.com/keys" target="_blank" rel="noreferrer" className="text-green-600 underline">
            Get a free key here
          </a>
        </p>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-1 rounded-full font-medium ${groqSet ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}>
            {groqSet ? "Key saved" : "Not set"}
          </span>
        </div>
        <input
          type="password"
          className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400 font-mono"
          placeholder="gsk_..."
          value={groqKey}
          onChange={(e) => setGroqKey(e.target.value)}
        />
        <button
          onClick={saveGroqKey}
          disabled={savingGroq || !groqKey.trim()}
          className="w-full py-2.5 bg-green-500 text-white rounded-xl text-sm font-medium hover:bg-green-600 disabled:opacity-50"
        >
          {savingGroq ? "Saving..." : groqSet ? "Update Key" : "Save Key"}
        </button>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4 space-y-3">
        <h3 className="font-semibold text-gray-800">
          Gemini API Key {provider === "gemini" && <span className="text-xs text-green-500">(active)</span>}
        </h3>
        <p className="text-xs text-gray-500">
          Only needed for the Gemini fallback models.{" "}
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
        <h3 className="font-semibold text-gray-800">USDA Food Database Key</h3>
        <p className="text-xs text-gray-500">
          Supplies the real macro/micro numbers. The AI only identifies ingredients;
          their nutrients are looked up in USDA FoodData Central.{" "}
          <a href="https://fdc.nal.usda.gov/api-key-signup" target="_blank" rel="noreferrer" className="text-green-600 underline">
            Get a free key here
          </a>.{" "}
          <span className="text-yellow-700">Recommended:</span> the shared DEMO_KEY is
          throttled to ~30/hr &amp; 50/day (a few meals exhaust it); a free signed key gives 1,000/hr.
        </p>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-1 rounded-full font-medium ${usdaSet ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}>
            {usdaSet ? "Key saved" : "Using DEMO_KEY"}
          </span>
        </div>
        <input
          type="password"
          className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400 font-mono"
          placeholder="USDA API key"
          value={usdaKey}
          onChange={(e) => setUsdaKey(e.target.value)}
        />
        <button
          onClick={saveUsdaKey}
          disabled={savingUsda || !usdaKey.trim()}
          className="w-full py-2.5 bg-green-500 text-white rounded-xl text-sm font-medium hover:bg-green-600 disabled:opacity-50"
        >
          {savingUsda ? "Saving..." : usdaSet ? "Update Key" : "Save Key"}
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
