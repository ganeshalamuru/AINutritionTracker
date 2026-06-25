import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import client from "../api/client";
import Toast from "../components/shared/Toast";
import ApiKeyCard from "../components/settings/ApiKeyCard";
import SettingsSection from "../components/settings/SettingsSection";
import { computeGoals, DEFAULT_CALORIE_GOAL } from "../utils/goals";

// Provider -> its selectable models. The provider dropdown picks the group; the
// model dropdown lists that group's `models`.
const PROVIDERS = [
  { id: "groq", label: "Groq (cloud)", models: [
    { model: "qwen/qwen3.6-27b", label: "Qwen 3.6 27B — fast vision, ~1k/day" },
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
  const { user, logout, updateUser } = useAuth();
  const navigate = useNavigate();
  const isAdmin = user.role === "admin";
  const [goalInput, setGoalInput] = useState(user.calorie_goal ?? DEFAULT_CALORIE_GOAL);
  const [savingGoal, setSavingGoal] = useState(false);
  const [keySet, setKeySet] = useState(false);
  const [groqSet, setGroqSet] = useState(false);
  const [usdaSet, setUsdaSet] = useState(false);
  const [nutritionSource, setNutritionSource] = useState("offline");
  const [provider, setProvider] = useState("groq");
  const [model, setModel] = useState("");
  const [savingModel, setSavingModel] = useState(false);
  const [toast, setToast] = useState(null);

  // The /config endpoint (API keys, provider/model, nutrition source) is admin-only; only
  // load it for admins. Non-admins don't see those sections at all.
  useEffect(() => {
    if (!isAdmin) return;
    client.get("/config").then((r) => {
      setKeySet(r.data.gemini_api_key_set);
      setGroqSet(r.data.groq_api_key_set);
      setUsdaSet(r.data.usda_api_key_set);
      setNutritionSource(r.data.nutrition_source || "offline");
      const p = r.data.vision_provider || "groq";
      setProvider(p);
      setModel(r.data.vision_model || modelsFor(p)[0]?.model || "");
    });
  }, [isAdmin]);

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

  // Persist the daily calorie goal on the signed-in user's account. Energy-linked macro
  // goals scale from it (see utils/goals.js).
  const saveGoal = async () => {
    const kcal = Math.round(Number(goalInput));
    if (!Number.isFinite(kcal) || kcal < 500 || kcal > 10000) {
      setToast({ message: "Enter a goal between 500 and 10000 kcal", type: "error" });
      return;
    }
    setSavingGoal(true);
    try {
      await client.patch("/users/me", { calorie_goal: kcal });
      updateUser({ calorie_goal: kcal });
      setGoalInput(kcal);
      setToast({ message: "Calorie goal updated!", type: "success" });
    } catch {
      setToast({ message: "Failed to update calorie goal", type: "error" });
    } finally {
      setSavingGoal(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="pt-4 space-y-6 pb-4">
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

      <h2 className="text-xl font-bold text-gray-900">Settings</h2>

      <SettingsSection title="Daily Goal" subtitle={`${goalInput} kcal`} defaultOpen>
        <div className="py-4 first:pt-0 last:pb-0 space-y-3">
          <p className="text-xs text-gray-500">
            Your target daily energy intake. Protein, carbs, fat, fiber and sugar goals scale
            with it; the sodium limit and vitamin/mineral targets stay fixed.
          </p>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                type="number"
                min={500}
                max={10000}
                step={50}
                inputMode="numeric"
                value={goalInput}
                onChange={(e) => setGoalInput(e.target.value)}
                className="w-full border border-gray-200 rounded-xl px-3 py-2.5 pr-12 text-sm focus:outline-none focus:border-green-400"
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">kcal</span>
            </div>
            <button
              onClick={saveGoal}
              disabled={savingGoal}
              className="px-4 py-2.5 rounded-xl bg-green-500 text-white text-sm font-medium hover:bg-green-600 disabled:opacity-50"
            >
              {savingGoal ? "Saving..." : "Save"}
            </button>
          </div>
          {(() => {
            const g = computeGoals(goalInput);
            return (
              <p className="text-xs text-gray-400">
                Targets: Protein {g.protein_g}g · Carbs {g.carbs_g}g · Fat {g.fat_g}g ·
                Fiber {g.fiber_g}g · Sugar {g.sugar_g}g
              </p>
            );
          })()}
        </div>
      </SettingsSection>

      {isAdmin && (
        <SettingsSection
          title="AI Vision"
          subtitle={`${(PROVIDERS.find((p) => p.id === provider)?.label || provider).split(" (")[0]} · ${(modelsFor(provider).find((m) => m.model === model)?.label || model).split(" — ")[0]}`}
        >
          <div className="py-4 first:pt-0 last:pb-0 space-y-3">
            <p className="text-xs text-gray-500">
              Model used to analyze meal photos. Groq · Qwen 3.6 27B is fast with the highest free daily limit.
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

          <div className="py-4 first:pt-0 last:pb-0">
            <ApiKeyCard
              bare
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
          </div>

          <div className="py-4 first:pt-0 last:pb-0">
            <ApiKeyCard
              bare
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
          </div>
        </SettingsSection>
      )}

      {isAdmin && (
        <SettingsSection
          title="Nutrition Data"
          subtitle={nutritionSource === "offline" ? "Local database" : "USDA API"}
        >
          <div className="py-4 first:pt-0 last:pb-0 space-y-3">
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

          <div className="py-4 first:pt-0 last:pb-0">
            <ApiKeyCard
              bare
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
          </div>
        </SettingsSection>
      )}

      <SettingsSection title="Account" subtitle={`@${user.username}`}>
        <div className="py-4 first:pt-0 last:pb-0 space-y-3">
          <div className="flex items-center gap-3">
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center text-white font-bold text-sm flex-shrink-0"
              style={{ backgroundColor: user.avatar_color }}
            >
              {user.name.charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate">{user.name}</p>
              <p className="text-xs text-gray-400 truncate">
                @{user.username}
                {isAdmin && <span className="ml-1 text-green-500 font-medium">· admin</span>}
              </p>
            </div>
          </div>
          <button
            onClick={() => navigate("/change-password")}
            className="w-full py-2.5 rounded-xl border border-gray-200 text-sm text-gray-700 hover:bg-gray-50"
          >
            Change password
          </button>
        </div>

        <div className="py-4 first:pt-0 last:pb-0">
          <h4 className="font-medium text-gray-700 text-sm mb-2">Access on Mobile</h4>
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
      </SettingsSection>

      <button
        onClick={handleLogout}
        className="w-full py-3 rounded-2xl border-2 border-gray-200 text-gray-600 text-sm font-medium hover:bg-gray-50"
      >
        Log out
      </button>
    </div>
  );
}
