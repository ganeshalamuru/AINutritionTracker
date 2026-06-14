import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProfile } from "../context/ProfileContext";
import client from "../api/client";
import Spinner from "../components/shared/Spinner";
import Toast from "../components/shared/Toast";
import MicroGrid from "../components/meal/MicroGrid";
import MacroHighlights from "../components/meal/MacroHighlights";
import { uid } from "../utils/uid";

// A dish's baseline portion: the model's dish grams, or the sum of its ingredient grams
// when the dish itself has no weight (decomposed dishes sometimes only weigh the parts).
const dishBaseline = (dish) =>
  dish.grams > 0 ? dish.grams : (dish.ingredients || []).reduce((s, i) => s + (i.grams || 0), 0);

// Re-sum the meal from each dish's per-dish nutrient subtotal, scaled by its edited
// portion (curGrams / baseGrams). The subtotals come from the immutable analysis, so
// scaling always derives from the original baseline and repeated edits never compound
// rounding. A dish's contribution is linear in its grams (whole-dish match or decomposed
// sum alike), so this is identical to re-running the USDA lookup — no network call needed.
// Dishes the user removed in review contribute nothing.
function scaledTotals(dishes, dishBase, dishGrams, dishRemoved, field) {
  const total = {};
  dishes.forEach((dish, i) => {
    if (dishRemoved[i]) return;
    const base = dishBase[i];
    const f = base > 0 ? (dishGrams[i] || 0) / base : 1;
    const vals = dish[field] || {};
    for (const k in vals) total[k] = (total[k] || 0) + vals[k] * f;
  });
  return total;
}

// Downscale a photo in the browser before upload — cuts input tokens, upload time,
// and latency. 384px keeps both dimensions ≤384 so vision APIs bill a flat ~258
// image tokens (no tiling), fitting comfortably under free-tier TPM limits. The
// model downsamples internally anyway. Falls back to the original file on failure.
async function downscaleImage(file, maxDim = 384, quality = 0.8) {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, maxDim / Math.max(bitmap.width, bitmap.height));
    const w = Math.round(bitmap.width * scale);
    const h = Math.round(bitmap.height * scale);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    canvas.getContext("2d").drawImage(bitmap, 0, 0, w, h);
    bitmap.close?.();
    const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", quality));
    return blob ? new File([blob], "meal.jpg", { type: "image/jpeg" }) : file;
  } catch {
    return file;
  }
}

export default function LogMeal() {
  const { profile } = useProfile();
  const navigate = useNavigate();
  const fileRef = useRef();
  const [photos, setPhotos] = useState([]);
  const [hint, setHint] = useState("");
  const [logging, setLogging] = useState(false);
  const [toast, setToast] = useState(null);

  // Just stage photos — no auto-analyze
  const handleFiles = (fileList) => {
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
  };

  const analyzePhoto = async (id, file) => {
    setPhotos((prev) => prev.map((p) => p.id === id ? { ...p, analyzing: true, error: null } : p));
    try {
      const fd = new FormData();
      fd.append("image", await downscaleImage(file));
      fd.append("profile_id", profile.id);
      if (hint.trim()) fd.append("user_note", hint.trim());
      const { data } = await client.post("/meals/analyze", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        // Local Ollama vision can take up to ~120s (backend OLLAMA_TIMEOUT) plus the USDA
        // lookups — far longer than client.js's global 45s. Override per-request so a slow
        // local model isn't cut off mid-analysis; cloud providers still finish well under it.
        timeout: 180000,
      });
      const dishBase = (data.dishes || []).map((d) => Math.round(dishBaseline(d)));
      setPhotos((prev) => prev.map((p) =>
        p.id === id
          ? {
              ...p, analyzing: false, analysis: data,
              mealName: data.meal_name, mealType: data.meal_type,
              // Editable portion state: baselines + current grams + per-dish removal +
              // live (edited) totals.
              dishBase,
              dishGrams: [...dishBase],
              dishRemoved: dishBase.map(() => false),
              liveMacros: data.macros,
              liveMicros: data.micros,
            }
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

  // Analyze all photos that don't have results yet (pending + previously errored)
  const analyzeAll = async () => {
    const toAnalyze = photos.filter((p) => !p.analysis && !p.analyzing);
    for (const photo of toAnalyze) {
      await analyzePhoto(photo.id, photo.file);
    }
  };

  const updatePhoto = (id, updates) =>
    setPhotos((prev) => prev.map((p) => p.id === id ? { ...p, ...updates } : p));

  // Edit a dish's portion grams; scale that dish proportionally and re-sum the meal.
  const setDishGrams = (id, dishIndex, grams) =>
    setPhotos((prev) => prev.map((p) => {
      if (p.id !== id || !p.analysis) return p;
      const dishGrams = [...p.dishGrams];
      dishGrams[dishIndex] = grams;
      const dishes = p.analysis.dishes || [];
      return {
        ...p,
        dishGrams,
        liveMacros: scaledTotals(dishes, p.dishBase, dishGrams, p.dishRemoved, "macros"),
        liveMicros: scaledTotals(dishes, p.dishBase, dishGrams, p.dishRemoved, "micros"),
      };
    }));

  // Remove (or restore) a dish from the analysis; re-sum the meal without it.
  const setDishRemoved = (id, dishIndex, removed) =>
    setPhotos((prev) => prev.map((p) => {
      if (p.id !== id || !p.analysis) return p;
      const dishRemoved = [...p.dishRemoved];
      dishRemoved[dishIndex] = removed;
      const dishes = p.analysis.dishes || [];
      return {
        ...p,
        dishRemoved,
        liveMacros: scaledTotals(dishes, p.dishBase, p.dishGrams, dishRemoved, "macros"),
        liveMicros: scaledTotals(dishes, p.dishBase, p.dishGrams, dishRemoved, "micros"),
      };
    }));

  const removePhoto = (id) =>
    setPhotos((prev) => prev.filter((p) => p.id !== id));

  const retryPhoto = (id) => {
    const photo = photos.find((p) => p.id === id);
    if (photo) analyzePhoto(id, photo.file);
  };

  const reset = () => {
    setPhotos([]);
    setHint("");
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
          macros: p.liveMacros || p.analysis.macros,
          micros: p.liveMicros || p.analysis.micros,
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
            macros: p.liveMacros || p.analysis.macros,
            micros: p.liveMicros || p.analysis.micros,
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
  const unanalyzed = photos.filter((p) => !p.analysis && !p.analyzing);
  const readyCount = photos.filter((p) => p.analysis).length;
  const hasPhotos = photos.length > 0;
  // Show analyze section when there are photos without results (pending or previously errored)
  const showAnalyzeSection = hasPhotos && unanalyzed.length > 0 && !isAnalyzing;
  const showLogSection = hasPhotos && !isAnalyzing && readyCount > 0 && unanalyzed.length === 0;

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
            <h2 className="text-xl font-bold text-gray-900">
              {isAnalyzing ? "Analyzing..." : showLogSection ? "Review & Log" : "Add context"}
            </h2>
            <button onClick={reset} className="text-sm text-gray-400 hover:text-gray-600">Start over</button>
          </div>

          {photos.map((photo) => (
            <PhotoCard
              key={photo.id}
              photo={photo}
              onUpdate={(updates) => updatePhoto(photo.id, updates)}
              onDishGrams={(dishIndex, grams) => setDishGrams(photo.id, dishIndex, grams)}
              onDishRemoved={(dishIndex, removed) => setDishRemoved(photo.id, dishIndex, removed)}
              onRemove={!isAnalyzing ? () => removePhoto(photo.id) : undefined}
              onRetry={() => retryPhoto(photo.id)}
            />
          ))}

          {/* Hint + Analyze — shown before analysis, hidden once all are done */}
          {(showAnalyzeSection || isAnalyzing) && (
            <div className="bg-gray-50 rounded-2xl p-4 space-y-3">
              <div>
                <label className="text-xs font-medium text-gray-600 mb-1.5 block">
                  Hint for AI <span className="font-normal text-gray-400">(optional)</span>
                </label>
                <input
                  className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-green-400 bg-white"
                  placeholder='e.g. "I only ate half", "small portion", "homemade dal rice"'
                  value={hint}
                  onChange={(e) => setHint(e.target.value)}
                  disabled={isAnalyzing}
                />
              </div>
              <button
                onClick={analyzeAll}
                disabled={isAnalyzing}
                className="w-full py-3.5 bg-green-500 text-white font-semibold rounded-2xl hover:bg-green-600 disabled:opacity-50 transition-colors text-base"
              >
                {isAnalyzing
                  ? "Analyzing..."
                  : `Analyze ${unanalyzed.length} photo${unanalyzed.length > 1 ? "s" : ""}`}
              </button>
              {!isAnalyzing && (
                <button
                  onClick={() => fileRef.current?.click()}
                  className="w-full py-2.5 border-2 border-dashed border-gray-300 rounded-2xl text-sm text-gray-500 hover:border-green-300 hover:text-green-600 hover:bg-green-50 transition-colors"
                >
                  + Add another photo
                </button>
              )}
            </div>
          )}

          {/* Log section — shown only after all photos are analyzed */}
          {showLogSection && (
            profile.isGuest ? (
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
                disabled={logging}
                className="w-full py-4 bg-green-500 text-white font-semibold rounded-2xl hover:bg-green-600 disabled:opacity-50 transition-colors text-base"
              >
                {logging
                  ? "Logging..."
                  : readyCount > 1
                    ? `Log ${readyCount} meals as a group`
                    : "Log this Meal"}
              </button>
            )
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

function PhotoCard({ photo, onUpdate, onDishGrams, onDishRemoved, onRemove, onRetry }) {
  // Live (portion-edited) totals when present, else the original analysis values.
  const macros = photo.liveMacros || photo.analysis?.macros;
  const micros = photo.liveMicros || photo.analysis?.micros;
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="relative">
        <img src={photo.previewUrl} alt="meal" className="w-full h-44 object-cover" />
        {onRemove && (
          <button
            onClick={onRemove}
            className="absolute top-2 right-2 bg-black/50 rounded-full w-8 h-8 flex items-center justify-center text-white text-sm"
          >
            ✕
          </button>
        )}
      </div>

      <div className="p-4 space-y-3">
        {photo.analyzing && <Spinner text="Analyzing..." />}

        {photo.error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-xs text-red-600">
            {photo.error}
            <button onClick={onRetry} className="ml-2 underline text-red-500 hover:text-red-700">Retry</button>
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
                <span className="font-bold text-gray-900">{Math.round(macros.calories)} kcal</span>
              </div>
              <MacroHighlights macros={macros} />
              <div className="grid grid-cols-3 gap-1.5 text-center text-xs">
                <div className="bg-white rounded-lg p-1.5">
                  <p className="font-bold text-blue-500">{Math.round(macros.protein_g)}g</p>
                  <p className="text-gray-400">Protein</p>
                </div>
                <div className="bg-white rounded-lg p-1.5">
                  <p className="font-bold text-orange-400">{Math.round(macros.carbs_g)}g</p>
                  <p className="text-gray-400">Carbs</p>
                </div>
                <div className="bg-white rounded-lg p-1.5">
                  <p className="font-bold text-purple-500">{Math.round(macros.fat_g)}g</p>
                  <p className="text-gray-400">Fat</p>
                </div>
              </div>
              <div className="flex justify-around mt-2 text-xs text-gray-400">
                <span>Fiber {Math.round(macros.fiber_g)}g</span>
                <span>Sugar {Math.round(macros.sugar_g)}g</span>
                <span>Sodium {Math.round(macros.sodium_mg)}mg</span>
              </div>
            </div>

            {photo.analysis.dishes?.length > 0 && (
              <div className="bg-gray-50 rounded-xl p-3">
                <span className="text-xs font-semibold text-gray-700 block mb-1">
                  Breakdown
                </span>
                <p className="text-[11px] text-gray-400 mb-2">
                  Green = found in the food database. A matched dish is counted whole; an
                  unmatched dish is counted from its ingredients. Adjust a portion (g) and
                  nutrition updates automatically.
                </p>
                <div className="space-y-2.5">
                  {photo.analysis.dishes.map((dish, i) => (
                    <DishRow
                      key={i}
                      dish={dish}
                      grams={photo.dishGrams?.[i]}
                      base={photo.dishBase?.[i]}
                      removed={photo.dishRemoved?.[i]}
                      onGrams={(g) => onDishGrams(i, g)}
                      onToggleRemove={(r) => onDishRemoved(i, r)}
                    />
                  ))}
                </div>
                {photo.analysis.unmatched?.length > 0 && (
                  <p className="text-xs text-yellow-700 mt-2.5">
                    Couldn't find {photo.analysis.unmatched.length} item
                    {photo.analysis.unmatched.length > 1 ? "s" : ""} in the food database —
                    totals may be undercounted.
                  </p>
                )}
                {photo.analysis.skipped?.length > 0 && (
                  <p className="text-xs text-gray-500 mt-1.5">
                    {photo.analysis.skipped.length} ingredient
                    {photo.analysis.skipped.length > 1 ? "s" : ""} over the lookup limit —
                    not counted.
                  </p>
                )}
              </div>
            )}

            <MicroGrid micros={micros} />

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

// Status colors for a decomposed ingredient (only used when its dish did NOT match).
const ING_STYLE = {
  matched: "bg-green-50 text-green-700",
  unmatched: "bg-yellow-100 text-yellow-700",
  skipped: "bg-gray-200 text-gray-500 line-through",
};

function DishRow({ dish, grams, base, removed, onGrams, onToggleRemove }) {
  // Editable portion. When there's no baseline weight (no dish grams and no ingredient
  // grams) there's nothing to scale from, so the field is locked and the factor stays 1.
  const locked = !(base > 0);
  const factor = locked ? 1 : (grams || 0) / base;
  return (
    <div className={removed ? "opacity-60" : ""}>
      {/* Dish header — highlighted green when the whole dish matched in USDA */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span
          className={`text-xs px-2 py-1 rounded-full font-medium ${
            removed
              ? "bg-gray-100 text-gray-400 line-through"
              : dish.matched ? "bg-green-100 text-green-800" : "bg-white text-gray-700 border border-gray-200"
          }`}
        >
          {dish.name}
        </span>
        <span className="flex items-center gap-0.5">
          <input
            type="number"
            min="0"
            inputMode="numeric"
            value={Number.isFinite(grams) ? grams : 0}
            onChange={(e) => onGrams(e.target.value === "" ? 0 : Math.max(0, Number(e.target.value)))}
            disabled={locked || removed}
            className="w-14 border border-gray-200 rounded-lg px-1.5 py-0.5 text-xs text-right focus:outline-none focus:border-green-400 disabled:bg-gray-100 disabled:text-gray-400"
          />
          <span className="text-[11px] text-gray-400">g</span>
        </span>
        {!removed && (dish.matched ? (
          <span className="text-[10px] text-green-700 font-medium">matched</span>
        ) : (
          <span className="text-[10px] text-gray-400">from ingredients</span>
        ))}
        {/* Remove / Undo toggle, pushed to the right */}
        {removed ? (
          <span className="ml-auto flex items-center gap-1.5">
            <span className="text-[10px] text-gray-400">removed</span>
            <button
              onClick={() => onToggleRemove(false)}
              className="text-[11px] text-green-600 font-medium hover:text-green-700"
            >
              Undo
            </button>
          </span>
        ) : (
          <button
            onClick={() => onToggleRemove(true)}
            className="ml-auto text-[11px] text-red-400 hover:text-red-500"
            title="Remove this dish from the meal"
          >
            Remove
          </button>
        )}
      </div>

      {/* Ingredients — de-emphasized when the dish matched (they weren't looked up),
          colored by their own USDA outcome when the dish was decomposed. Grams scale
          with the dish portion. Greyed out when the dish is removed. */}
      {dish.ingredients?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1 pl-3">
          {dish.ingredients.map((ing, i) => {
            const g = Math.round((ing.grams || 0) * factor);
            const style = removed || dish.matched
              ? "bg-transparent text-gray-400"
              : ING_STYLE[ing.status] || "bg-white text-gray-600";
            return (
              <span key={i} className={`text-[11px] px-1.5 py-0.5 rounded-full ${style}`}>
                {ing.food}{g > 0 ? ` · ${g}g` : ""}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
