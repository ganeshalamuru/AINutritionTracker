import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useProfile } from "../context/ProfileContext";
import client from "../api/client";
import Toast from "../components/shared/Toast";
import ConfirmModal from "../components/shared/ConfirmModal";
import ApiKeyCard from "../components/settings/ApiKeyCard";

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

export default function Settings() {
  const { profile, logout } = useProfile();
  const navigate = useNavigate();
  const [keySet, setKeySet] = useState(false);
  const [groqSet, setGroqSet] = useState(false);
  const [usdaSet, setUsdaSet] = useState(false);
  const [nutritionSource, setNutritionSource] = useState("offline");
  const [provider, setProvider] = useState("groq");
  const [model, setModel] = useState("");
  const [savingModel, setSavingModel] = useState(false);
  const [profiles, setProfiles] = useState([]);
  const [toast, setToast] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);

  useEffect(() => {
    client.get("/config").then((r) => {
      setKeySet(r.data.gemini_api_key_set);
      setGroqSet(r.data.groq_api_key_set);
      setUsdaSet(r.data.usda_api_key_set);
      setNutritionSource(r.data.nutrition_source || "offline");
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

  // Where Stage 2 gets nutrient numbers: "offline" (local USDA database, no network) or
  // "online" (USDA FoodData Central API). Optimistic update, reverts on failure.
  const saveNutritionSource = async (src) => {
    if (src === nutritionSource) return;
    const prev = nutritionSource;
    setNutritionSource(src);
    try {
      await client.put("/config", { nutrition_source: src });
      setToast({ message: src === "offline" ? "Using local database" : "Using USDA API", type: "success" });
    } catch {
      setNutritionSource(prev);
      setToast({ message: "Failed to switch nutrition source", type: "error" });
    }
  };

  // Persist a single API key. ApiKeyCard owns the input + saving state and only renders
  // here; on success we flip the matching "is set" flag and toast. Throwing on failure lets
  // the card clear its saving state without wiping the typed value.
  const makeKeySaver = (field, markSet, savedMessage) => async (value) => {
    try {
      await client.put("/config", { [field]: value });
      markSet(true);
      setToast({ message: savedMessage, type: "success" });
    } catch {
      setToast({ message: "Failed to save key", type: "error" });
      throw new Error("save failed");
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

      <ApiKeyCard
        title="Groq API Key"
        active={provider === "groq"}
        isSet={groqSet}
        placeholder="gsk_..."
        onSave={makeKeySaver("groq_api_key", setGroqSet, "Groq key saved!")}
      >
        Used by the Groq vision provider.{" "}
        <a href="https://console.groq.com/keys" target="_blank" rel="noreferrer" className="text-green-600 underline">
          Get a free key here
        </a>
      </ApiKeyCard>

      <ApiKeyCard
        title="Gemini API Key"
        active={provider === "gemini"}
        isSet={keySet}
        placeholder="AIza..."
        onSave={makeKeySaver("gemini_api_key", setKeySet, "API key saved!")}
      >
        Only needed for the Gemini fallback models.{" "}
        <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="text-green-600 underline">
          Get a free key here
        </a>
      </ApiKeyCard>

      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4 space-y-3">
        <h3 className="font-semibold text-gray-800">Nutrition Data Source</h3>
        <p className="text-xs text-gray-500">
          Where the real macro/micro numbers come from. The AI only identifies ingredients;
          their nutrients are looked up in USDA FoodData Central — either from a local copy
          (offline, no rate limits) or the live API.
        </p>
        <div className="grid grid-cols-2 gap-2">
          {[
            { id: "offline", label: "Local database", sub: "Offline · no limits" },
            { id: "online", label: "USDA API", sub: "Live · needs key" },
          ].map((opt) => (
            <button
              key={opt.id}
              onClick={() => saveNutritionSource(opt.id)}
              className={`rounded-xl border-2 px-3 py-2.5 text-left ${
                nutritionSource === opt.id
                  ? "border-green-400 bg-green-50"
                  : "border-gray-200 hover:bg-gray-50"
              }`}
            >
              <span className="block text-sm font-medium text-gray-800">{opt.label}</span>
              <span className="block text-xs text-gray-500">{opt.sub}</span>
            </button>
          ))}
        </div>
        {nutritionSource === "offline" && (
          <p className="text-xs text-gray-400">
            Built once from the bundled USDA dataset via{" "}
            <span className="font-mono text-gray-500">python build_usda_db.py</span>. The USDA API
            key below is only used in online mode.
          </p>
        )}
      </div>

      <ApiKeyCard
        title="USDA Food Database Key"
        active={nutritionSource === "online"}
        isSet={usdaSet}
        unsetLabel="Using DEMO_KEY"
        placeholder="USDA API key"
        onSave={makeKeySaver("usda_api_key", setUsdaSet, "USDA key saved!")}
      >
        Used only when the nutrition source above is <strong>USDA API</strong>. Supplies the real
        macro/micro numbers from USDA FoodData Central.{" "}
        <a href="https://fdc.nal.usda.gov/api-key-signup" target="_blank" rel="noreferrer" className="text-green-600 underline">
          Get a free key here
        </a>.{" "}
        <span className="text-yellow-700">Recommended:</span> the shared DEMO_KEY is
        throttled to ~30/hr &amp; 50/day (a few meals exhaust it); a free signed key gives 1,000/hr.
      </ApiKeyCard>

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
