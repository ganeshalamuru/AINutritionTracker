import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProfile } from "../context/ProfileContext";
import client from "../api/client";
import Spinner from "../components/shared/Spinner";
import Toast from "../components/shared/Toast";
import MicroGrid from "../components/meal/MicroGrid";

const MEAL_TYPES = ["breakfast", "lunch", "dinner", "snack"];

const uid = () => Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);

export default function LogMeal() {
  const { profile } = useProfile();
  const navigate = useNavigate();
  const fileRef = useRef();
  const [photos, setPhotos] = useState([]);
  const [logging, setLogging] = useState(false);
  const [toast, setToast] = useState(null);

  const handleFiles = async (fileList) => {
    const newPhotos = Array.from(fileList).map((file) => ({
      id: uid(),
      file,
      previewUrl: URL.createObjectURL(file),
      analysis: null,
      analyzing: false,
      error: null,
      mealName: "",
      mealType: "snack",
      notes: "",
    }));
    setPhotos((prev) => [...prev, ...newPhotos]);

    for (const photo of newPhotos) {
      await analyzePhoto(photo.id, photo.file);
    }
  };

  const analyzePhoto = async (id, file) => {
    setPhotos((prev) => prev.map((p) => p.id === id ? { ...p, analyzing: true } : p));
    try {
      const fd = new FormData();
      fd.append("image", file);
      fd.append("profile_id", profile.id);
      const { data } = await client.post("/meals/analyze", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setPhotos((prev) => prev.map((p) =>
        p.id === id
          ? { ...p, analyzing: false, analysis: data, mealName: data.meal_name, mealType: data.meal_type }
          : p
      ));
    } catch (err) {
      setPhotos((prev) => prev.map((p) =>
        p.id === id
          ? { ...p, analyzing: false, error: err.response?.data?.detail || "Analysis failed. Check your API key in Settings." }
          : p
      ));
    }
  };

  const updatePhoto = (id, updates) =>
    setPhotos((prev) => prev.map((p) => p.id === id ? { ...p, ...updates } : p));

  const removePhoto = (id) =>
    setPhotos((prev) => prev.filter((p) => p.id !== id));

  const reset = () => {
    setPhotos([]);
    if (fileRef.current) fileRef.current.value = "";
  };

  const handleLog = async () => {
    const ready = photos.filter((p) => p.analysis && !p.analyzing);
    if (!ready.length) return;

    setLogging(true);
    try {
      if (ready.length === 1) {
        const p = ready[0];
        await client.post("/meals/log", {
          profile_id: profile.id,
          meal_name: p.mealName,
          meal_type: p.mealType,
          notes: p.notes,
          keep_image: false,
          temp_image_token: p.analysis.temp_image_token,
          macros: p.analysis.macros,
          micros: p.analysis.micros,
        });
      } else {
        const groupId = uid();
        await client.post("/meals/log-group", {
          group_id: groupId,
          meals: ready.map((p) => ({
            profile_id: profile.id,
            meal_name: p.mealName,
            meal_type: p.mealType,
            notes: p.notes,
            keep_image: false,
            temp_image_token: p.analysis.temp_image_token,
            macros: p.analysis.macros,
            micros: p.analysis.micros,
          })),
        });
      }
      setToast({ message: ready.length > 1 ? `${ready.length} meals logged!` : "Meal logged!", type: "success" });
      setTimeout(() => navigate("/home"), 1200);
    } catch {
      setToast({ message: "Failed to log meal", type: "error" });
    } finally {
      setLogging(false);
    }
  };

  const isAnalyzing = photos.some((p) => p.analyzing);
  const readyCount = photos.filter((p) => p.analysis && !p.analyzing).length;
  const hasPhotos = photos.length > 0;

  return (
    <div className="pt-4 pb-4">
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

      {!hasPhotos && (
        <div>
          <h2 className="text-xl font-bold text-gray-900 mb-1">Log a Meal</h2>
          <p className="text-sm text-gray-500 mb-6">Take photos or upload from your gallery — add multiple for a full meal</p>
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
              <p className="font-semibold text-gray-700">Tap to add photos</p>
              <p className="text-sm text-gray-500">Select one or multiple images</p>
            </div>
          </div>
        </div>
      )}

      {hasPhotos && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-bold text-gray-900">Review & Log</h2>
            <button onClick={reset} className="text-sm text-gray-400 hover:text-gray-600">Start over</button>
          </div>

          {photos.map((photo) => (
            <PhotoCard
              key={photo.id}
              photo={photo}
              onUpdate={(updates) => updatePhoto(photo.id, updates)}
              onRemove={() => removePhoto(photo.id)}
            />
          ))}

          <button
            onClick={() => fileRef.current?.click()}
            className="w-full py-3 border-2 border-dashed border-gray-300 rounded-2xl text-sm text-gray-500 hover:border-green-300 hover:text-green-600 hover:bg-green-50 transition-colors"
          >
            + Add another photo
          </button>

          {profile.isGuest ? (
            <div className="bg-green-50 border border-green-200 rounded-2xl p-4 text-center">
              <p className="text-sm text-green-800 font-medium mb-2">Create a profile to save meals</p>
              <button
                onClick={() => navigate("/")}
                className="bg-green-500 text-white px-6 py-2 rounded-xl text-sm font-medium hover:bg-green-600"
              >
                Create Profile
              </button>
            </div>
          ) : (
            <button
              onClick={handleLog}
              disabled={logging || isAnalyzing || !readyCount}
              className="w-full py-4 bg-green-500 text-white font-semibold rounded-2xl hover:bg-green-600 disabled:opacity-50 transition-colors text-base"
            >
              {logging
                ? "Logging..."
                : isAnalyzing
                  ? "Analyzing..."
                  : readyCount > 1
                    ? `Log ${readyCount} meals as a group`
                    : "Log this Meal"}
            </button>
          )}
        </div>
      )}

      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(e) => { if (e.target.files?.length) handleFiles(e.target.files); e.target.value = ""; }}
      />
    </div>
  );
}

function PhotoCard({ photo, onUpdate, onRemove }) {
  const [showMicros, setShowMicros] = useState(false);

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="relative">
        <img src={photo.previewUrl} alt="meal" className="w-full h-44 object-cover" />
        <button
          onClick={onRemove}
          className="absolute top-2 right-2 bg-black/50 rounded-full w-8 h-8 flex items-center justify-center text-white text-sm"
        >
          ✕
        </button>
      </div>

      <div className="p-4 space-y-3">
        {photo.analyzing && <Spinner text="Analyzing..." />}

        {photo.error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-xs text-red-600">
            {photo.error}
          </div>
        )}

        {photo.analysis && !photo.analyzing && (
          <>
            {photo.analysis.confidence === "low" && (
              <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-3 text-xs text-yellow-700">
                Low confidence — image was unclear. Values may be estimates.
              </div>
            )}

            <div>
              <label className="text-xs text-gray-500 mb-1 block">Meal name</label>
              <input
                className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-green-400 font-medium"
                value={photo.mealName}
                onChange={(e) => onUpdate({ mealName: e.target.value })}
              />
            </div>

            <div>
              <label className="text-xs text-gray-500 mb-1.5 block">Meal type</label>
              <div className="flex gap-2 flex-wrap">
                {["breakfast", "lunch", "dinner", "snack"].map((t) => (
                  <button
                    key={t}
                    onClick={() => onUpdate({ mealType: t })}
                    className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${photo.mealType === t ? "bg-green-500 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>

            <div className="bg-gray-50 rounded-xl p-3">
              <div className="flex justify-between items-center mb-2">
                <span className="text-xs font-semibold text-gray-700">Macros</span>
                <span className="font-bold text-gray-900">{Math.round(photo.analysis.macros.calories)} kcal</span>
              </div>
              <div className="grid grid-cols-3 gap-1.5 text-center text-xs">
                <div className="bg-white rounded-lg p-1.5">
                  <p className="font-bold text-blue-500">{Math.round(photo.analysis.macros.protein_g)}g</p>
                  <p className="text-gray-400">Protein</p>
                </div>
                <div className="bg-white rounded-lg p-1.5">
                  <p className="font-bold text-orange-400">{Math.round(photo.analysis.macros.carbs_g)}g</p>
                  <p className="text-gray-400">Carbs</p>
                </div>
                <div className="bg-white rounded-lg p-1.5">
                  <p className="font-bold text-purple-500">{Math.round(photo.analysis.macros.fat_g)}g</p>
                  <p className="text-gray-400">Fat</p>
                </div>
              </div>
              <div className="flex justify-around mt-2 text-xs text-gray-400">
                <span>Fiber {Math.round(photo.analysis.macros.fiber_g)}g</span>
                <span>Sugar {Math.round(photo.analysis.macros.sugar_g)}g</span>
                <span>Sodium {Math.round(photo.analysis.macros.sodium_mg)}mg</span>
              </div>
            </div>

            <button
              onClick={() => setShowMicros((v) => !v)}
              className="text-xs text-green-600 font-medium flex items-center gap-1"
            >
              {showMicros ? "Hide micronutrients" : "Show micronutrients"}
              <svg xmlns="http://www.w3.org/2000/svg" className={`w-3 h-3 transition-transform ${showMicros ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {showMicros && <MicroGrid micros={photo.analysis.micros} />}

            <div>
              <label className="text-xs text-gray-500 mb-1 block">Notes (optional)</label>
              <input
                className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-green-400"
                placeholder="Any notes..."
                value={photo.notes}
                onChange={(e) => onUpdate({ notes: e.target.value })}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
