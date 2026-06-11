import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useProfile } from "../context/ProfileContext";
import client from "../api/client";
import Spinner from "../components/shared/Spinner";
import Toast from "../components/shared/Toast";
import MicroGrid from "../components/meal/MicroGrid";

const MEAL_TYPES = ["breakfast", "lunch", "dinner", "snack"];

export default function LogMeal() {
  const { profile } = useProfile();
  const navigate = useNavigate();
  const fileRef = useRef();
  const [preview, setPreview] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState(null);
  const [mealName, setMealName] = useState("");
  const [mealType, setMealType] = useState("snack");
  const [notes, setNotes] = useState("");
  const [logging, setLogging] = useState(false);
  const [toast, setToast] = useState(null);

  const handleFile = (file) => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setPreview(url);
    setResult(null);
    analyzeImage(file);
  };

  const analyzeImage = async (file) => {
    setAnalyzing(true);
    try {
      const fd = new FormData();
      fd.append("image", file);
      fd.append("profile_id", profile.id);
      const { data } = await client.post("/meals/analyze", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(data);
      setMealName(data.meal_name);
      setMealType(data.meal_type);
    } catch (err) {
      setToast({ message: err.response?.data?.detail || "Analysis failed. Check your API key in Settings.", type: "error" });
    } finally {
      setAnalyzing(false);
    }
  };

  const handleLog = async () => {
    if (!result) return;
    setLogging(true);
    try {
      await client.post("/meals/log", {
        profile_id: profile.id,
        meal_name: mealName,
        meal_type: mealType,
        notes,
        keep_image: false,
        temp_image_token: result.temp_image_token,
        macros: result.macros,
        micros: result.micros,
      });
      setToast({ message: "Meal logged!", type: "success" });
      setTimeout(() => navigate("/home"), 1200);
    } catch (err) {
      setToast({ message: "Failed to log meal", type: "error" });
    } finally {
      setLogging(false);
    }
  };

  const reset = () => {
    setPreview(null);
    setResult(null);
    setMealName("");
    setNotes("");
  };

  return (
    <div className="pt-4 pb-4">
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

      {!preview && (
        <div>
          <h2 className="text-xl font-bold text-gray-900 mb-1">Log a Meal</h2>
          <p className="text-sm text-gray-500 mb-6">Take a photo or upload from your gallery</p>
          <div
            onClick={() => fileRef.current?.click()}
            className="border-2 border-dashed border-green-300 rounded-3xl p-10 flex flex-col items-center gap-4 cursor-pointer hover:bg-green-50 transition-colors"
          >
            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center">
              <svg xmlns="http://www.w3.org/2000/svg" className="w-8 h-8 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </div>
            <div className="text-center">
              <p className="font-semibold text-gray-700">Tap to take a photo</p>
              <p className="text-sm text-gray-500">or upload from gallery</p>
            </div>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={(e) => handleFile(e.target.files[0])}
          />
        </div>
      )}

      {preview && (
        <div>
          <div className="relative rounded-2xl overflow-hidden mb-4">
            <img src={preview} alt="meal" className="w-full max-h-56 object-cover" />
            <button
              onClick={reset}
              className="absolute top-2 right-2 bg-black/50 rounded-full w-8 h-8 flex items-center justify-center text-white"
            >
              ✕
            </button>
          </div>

          {analyzing && <Spinner text="Analyzing your meal..." />}

          {result && !analyzing && (
            <div className="space-y-4">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Meal name</label>
                <input
                  className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400 font-medium"
                  value={mealName}
                  onChange={(e) => setMealName(e.target.value)}
                />
              </div>

              <div>
                <label className="text-xs text-gray-500 mb-2 block">Meal type</label>
                <div className="flex gap-2 flex-wrap">
                  {MEAL_TYPES.map((t) => (
                    <button
                      key={t}
                      onClick={() => setMealType(t)}
                      className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${mealType === t ? "bg-green-500 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              {result.confidence === "low" && (
                <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-3 text-xs text-yellow-700">
                  Low confidence — image was unclear. Values may be estimates.
                </div>
              )}

              <div className="bg-gray-50 rounded-2xl p-4">
                <div className="flex justify-between items-center mb-3">
                  <span className="font-semibold text-gray-800">Macros</span>
                  <span className="text-lg font-bold text-gray-900">{Math.round(result.macros.calories)} kcal</span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center text-sm">
                  <div className="bg-white rounded-xl p-2">
                    <p className="font-bold text-blue-500">{Math.round(result.macros.protein_g)}g</p>
                    <p className="text-xs text-gray-500">Protein</p>
                  </div>
                  <div className="bg-white rounded-xl p-2">
                    <p className="font-bold text-orange-400">{Math.round(result.macros.carbs_g)}g</p>
                    <p className="text-xs text-gray-500">Carbs</p>
                  </div>
                  <div className="bg-white rounded-xl p-2">
                    <p className="font-bold text-purple-500">{Math.round(result.macros.fat_g)}g</p>
                    <p className="text-xs text-gray-500">Fat</p>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center text-xs mt-2 text-gray-500">
                  <span>Fiber: {Math.round(result.macros.fiber_g)}g</span>
                  <span>Sugar: {Math.round(result.macros.sugar_g)}g</span>
                  <span>Sodium: {Math.round(result.macros.sodium_mg)}mg</span>
                </div>
              </div>

              <MicroGrid micros={result.micros} />

              <div>
                <label className="text-xs text-gray-500 mb-1 block">Notes (optional)</label>
                <input
                  className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400"
                  placeholder="Any notes..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </div>

              {profile.isGuest ? (
                <div className="bg-green-50 border border-green-200 rounded-2xl p-4 text-center">
                  <p className="text-sm text-green-800 font-medium mb-2">Create a profile to save this meal</p>
                  <button
                    onClick={() => { navigate("/"); }}
                    className="bg-green-500 text-white px-6 py-2 rounded-xl text-sm font-medium hover:bg-green-600"
                  >
                    Create Profile
                  </button>
                </div>
              ) : (
                <button
                  onClick={handleLog}
                  disabled={logging}
                  className="w-full py-4 bg-green-500 text-white font-semibold rounded-2xl hover:bg-green-600 disabled:opacity-50 transition-colors text-base"
                >
                  {logging ? "Logging..." : "Log this Meal"}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
