import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProfile } from "../context/ProfileContext";
import { useLogDraft } from "../context/LogDraftContext";
import client from "../api/client";
import Spinner from "../components/shared/Spinner";
import Toast from "../components/shared/Toast";
import MicroGrid from "../components/meal/MicroGrid";
import MacroHighlights from "../components/meal/MacroHighlights";
import { uid } from "../utils/uid";

// Cap a single meal log at 4 photos — keeps the multi-photo analyze burst within free-tier
// rate limits and the review screen scannable.
const MAX_PHOTOS = 4;

// A dish's baseline portion: the model's dish grams, or the sum of its ingredient grams
// when the dish itself has no weight (decomposed dishes sometimes only weigh the parts).
const dishBaseline = (dish) =>
  dish.grams > 0 ? dish.grams : (dish.ingredients || []).reduce((s, i) => s + (i.grams || 0), 0);

// Build the editable review draft from a fresh analysis. A draft holds the *editable* shape
// the review UI mutates (dish portion, per-ingredient grams, removals, custom adds); the
// immutable analysis stays the baseline we scale from, so repeated edits never compound
// rounding. Editing granularity is split by dish type (the "clean split"):
//   - matched dish  → the *dish* is the unit: one editable dish-grams field scales the whole
//                     dish subtotal. Its detected ingredients were never looked up, so they
//                     stay read-only chips. Custom-added ingredients are additive on top.
//   - decomposed dish → the *ingredient* is the unit: each resolved ingredient carries its own
//                     nutrients and is individually editable/removable; the dish grams is a
//                     derived (read-only) sum.
function buildDraft(data) {
  return (data.dishes || []).map((dish) => {
    const baseGrams = Math.round(dishBaseline(dish));
    return {
      name: dish.name,
      matched: dish.matched,
      baseGrams,
      grams: baseGrams, // editable for matched dishes; derived for decomposed
      macros: dish.macros || {},
      micros: dish.micros || {},
      removed: false,
      ingredients: (dish.ingredients || []).map((ing) => ({
        id: uid(),
        food: ing.food,
        status: ing.status,
        baseGrams: ing.grams || 0,
        grams: ing.grams || 0,
        macros: ing.macros || {},
        micros: ing.micros || {},
        removed: false,
        custom: false,
      })),
    };
  });
}

// A detected ingredient of a decomposed dish only carries nutrients when USDA resolved it
// (status "matched"); unmatched/skipped contribute nothing, so editing their grams is a no-op
// and the field is locked. Custom adds always carry their own nutrients.
const ingHasNutrients = (ing) => ing.custom || ing.status === "matched";

// Re-sum the meal from the draft. A matched dish contributes its whole subtotal scaled by the
// edited dish portion (grams/baseGrams). A decomposed dish — and any custom add on either kind —
// contributes per-ingredient (each ingredient's own subtotal scaled by its own grams/baseGrams).
// Detected ingredients of a matched dish are already inside the dish subtotal, so they're skipped
// here. Removed dishes/ingredients contribute nothing. Linear in grams, so identical to re-running
// the USDA lookup — no network call. Seeded with the full zeroed key set from `seed` (the analysis
// macros/micros) so every field is always present — totals stay a complete object (all zeros) even
// when the user removes everything, instead of a sparse object that would render NaN.
function draftTotals(draft, field, seed) {
  const total = {};
  for (const k in seed || {}) total[k] = 0;
  const add = (vals, f) => {
    for (const k in vals) total[k] = (total[k] || 0) + vals[k] * f;
  };
  (draft || []).forEach((dish) => {
    if (dish.removed) return;
    if (dish.matched) {
      const f = dish.baseGrams > 0 ? (dish.grams || 0) / dish.baseGrams : 1;
      add(dish[field] || {}, f);
    }
    dish.ingredients.forEach((ing) => {
      if (ing.removed) return;
      if (dish.matched && !ing.custom) return; // already counted inside the dish subtotal
      const f = ing.baseGrams > 0 ? (ing.grams || 0) / ing.baseGrams : 1;
      add(ing[field] || {}, f);
    });
  });
  return total;
}

// Immutable draft updaters — map down to the dish/ingredient being changed.
const mapDish = (draft, dishIndex, fn) =>
  draft.map((d, i) => (i === dishIndex ? fn(d) : d));
const mapIngredient = (dish, ingId, fn) => ({
  ...dish,
  ingredients: dish.ingredients.map((ing) => (ing.id === ingId ? fn(ing) : ing)),
});

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
  // Photos live in a context above the router so the in-progress log survives switching tabs
  // and coming back (LogMeal unmounts on navigation).
  const { photos, setPhotos } = useLogDraft();
  const [logging, setLogging] = useState(false);
  const [toast, setToast] = useState(null);

  // Just stage photos — no auto-analyze. Cap the total at MAX_PHOTOS: take only what fits and
  // toast about the rest rather than silently dropping them.
  const handleFiles = (fileList) => {
    const incoming = Array.from(fileList);
    const room = MAX_PHOTOS - photos.length;
    if (room <= 0) {
      setToast({ message: `Up to ${MAX_PHOTOS} photos per meal`, type: "error" });
      return;
    }
    const accepted = incoming.slice(0, room);
    if (accepted.length < incoming.length) {
      setToast({ message: `Up to ${MAX_PHOTOS} photos per meal`, type: "error" });
    }
    const newPhotos = accepted.map((file) => ({
      id: uid(),
      file,
      previewUrl: URL.createObjectURL(file),
      analysis: null,
      analyzing: false,
      error: null,
      hint: "",
      mealName: "",
      mealType: "snack",
      notes: "",
    }));
    setPhotos((prev) => [...prev, ...newPhotos]);
  };

  const analyzePhoto = async (id, file, hint = "") => {
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
      const draft = buildDraft(data);
      setPhotos((prev) => prev.map((p) =>
        p.id === id
          ? {
              ...p, analyzing: false, analysis: data,
              mealName: data.meal_name, mealType: data.meal_type,
              // Editable review state + live (edited) totals derived from it.
              draft,
              liveMacros: draftTotals(draft, "macros", data.macros),
              liveMicros: draftTotals(draft, "micros", data.micros),
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

  // Analyze all photos that don't have results yet (pending + previously errored), each with
  // its own hint.
  const analyzeAll = async () => {
    const toAnalyze = photos.filter((p) => !p.analysis && !p.analyzing);
    for (const photo of toAnalyze) {
      await analyzePhoto(photo.id, photo.file, photo.hint);
    }
  };

  const updatePhoto = (id, updates) =>
    setPhotos((prev) => prev.map((p) => p.id === id ? { ...p, ...updates } : p));

  // Apply a draft transform to one photo and re-derive the live meal totals from it.
  const mutateDraft = (id, fn) =>
    setPhotos((prev) => prev.map((p) => {
      if (p.id !== id || !p.draft) return p;
      const draft = fn(p.draft);
      return {
        ...p,
        draft,
        liveMacros: draftTotals(draft, "macros", p.analysis.macros),
        liveMicros: draftTotals(draft, "micros", p.analysis.micros),
      };
    }));

  // Edit a matched dish's portion grams (scales the whole dish subtotal).
  const onDishGrams = (id, di, grams) =>
    mutateDraft(id, (draft) => mapDish(draft, di, (d) => ({ ...d, grams })));
  // Remove (or restore) a whole dish — excludes it and all its ingredients from the total.
  const onDishRemoved = (id, di, removed) =>
    mutateDraft(id, (draft) => mapDish(draft, di, (d) => ({ ...d, removed })));
  // Edit one ingredient's grams (decomposed-dish ingredient or a custom add).
  const onIngGrams = (id, di, ingId, grams) =>
    mutateDraft(id, (draft) => mapDish(draft, di, (d) => mapIngredient(d, ingId, (ing) => ({ ...ing, grams }))));
  // Remove (or restore) a single ingredient.
  const onIngRemoved = (id, di, ingId, removed) =>
    mutateDraft(id, (draft) => mapDish(draft, di, (d) => mapIngredient(d, ingId, (ing) => ({ ...ing, removed }))));
  // Append a custom (user-searched) ingredient to a dish.
  const onAddIngredient = (id, di, ingredient) =>
    mutateDraft(id, (draft) => mapDish(draft, di, (d) => ({ ...d, ingredients: [...d.ingredients, ingredient] })));

  const removePhoto = (id) =>
    setPhotos((prev) => prev.filter((p) => p.id !== id));

  // Retry a failed analysis, or deliberately re-analyze a photo that already has a result
  // (e.g. after editing its hint). A fresh analysis rebuilds the draft, discarding manual edits.
  const retryPhoto = (id) => {
    const photo = photos.find((p) => p.id === id);
    if (photo) analyzePhoto(id, photo.file, photo.hint);
  };

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
      // Clear the persisted draft once it's saved — otherwise the logged photos would linger in
      // the context and reappear on the next visit to /log.
      setTimeout(() => { reset(); navigate("/home"); }, 1200);
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
  const atCapacity = photos.length >= MAX_PHOTOS;
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
              onDishGrams={(di, g) => onDishGrams(photo.id, di, g)}
              onDishRemoved={(di, removed) => onDishRemoved(photo.id, di, removed)}
              onIngGrams={(di, ingId, g) => onIngGrams(photo.id, di, ingId, g)}
              onIngRemoved={(di, ingId, removed) => onIngRemoved(photo.id, di, ingId, removed)}
              onAddIngredient={(di, ingredient) => onAddIngredient(photo.id, di, ingredient)}
              onRemove={!isAnalyzing ? () => removePhoto(photo.id) : undefined}
              onRetry={() => retryPhoto(photo.id)}
            />
          ))}

          {/* Analyze — shown before analysis, hidden once all are done. Each photo carries its
              own hint (edited on its card), so there's no shared hint box here anymore. */}
          {(showAnalyzeSection || isAnalyzing) && (
            <div className="bg-gray-50 rounded-2xl p-4 space-y-3">
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
                atCapacity ? (
                  <p className="text-center text-xs text-gray-400 py-1">
                    Maximum {MAX_PHOTOS} photos per meal
                  </p>
                ) : (
                  <button
                    onClick={() => fileRef.current?.click()}
                    className="w-full py-2.5 border-2 border-dashed border-gray-300 rounded-2xl text-sm text-gray-500 hover:border-green-300 hover:text-green-600 hover:bg-green-50 transition-colors"
                  >
                    + Add another photo
                  </button>
                )
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

function PhotoCard({ photo, onUpdate, onDishGrams, onDishRemoved, onIngGrams, onIngRemoved, onAddIngredient, onRemove, onRetry }) {
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

        {/* Per-photo hint for the AI — editable before analysis and after, so it can drive a
            re-analyze. Once a result exists, a Re-analyze button reruns Stage 1+2 with this hint
            (rebuilding the draft, discarding manual edits to this photo). */}
        {!photo.analyzing && (
          <div>
            <label className="text-xs font-medium text-gray-600 mb-1.5 block">
              Hint for AI <span className="font-normal text-gray-400">(optional)</span>
            </label>
            <input
              className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-green-400 bg-white"
              placeholder='e.g. "I only ate half", "small portion", "homemade dal rice"'
              value={photo.hint}
              onChange={(e) => onUpdate({ hint: e.target.value })}
            />
            {photo.analysis && (
              <button
                onClick={onRetry}
                className="mt-2 w-full py-2 border border-green-200 text-green-600 font-medium rounded-xl text-sm hover:bg-green-50 transition-colors"
              >
                Re-analyze with this hint
              </button>
            )}
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

            {photo.draft?.length > 0 && (
              <div className="bg-gray-50 rounded-xl p-3">
                <span className="text-xs font-semibold text-gray-700 block mb-1">
                  Breakdown
                </span>
                <p className="text-[11px] text-gray-400 mb-2">
                  Green = found in the food database. A matched dish is counted whole (edit its
                  portion); an unmatched dish is counted from its ingredients (edit each one).
                  Add or remove items and nutrition updates automatically.
                </p>
                <div className="space-y-2.5">
                  {photo.draft.map((dish, i) => (
                    <DishRow
                      key={i}
                      dish={dish}
                      onDishGrams={(g) => onDishGrams(i, g)}
                      onDishRemoved={(r) => onDishRemoved(i, r)}
                      onIngGrams={(ingId, g) => onIngGrams(i, ingId, g)}
                      onIngRemoved={(ingId, r) => onIngRemoved(i, ingId, r)}
                      onAddIngredient={(ingredient) => onAddIngredient(i, ingredient)}
                    />
                  ))}
                </div>
                {photo.analysis.unmatched?.length > 0 && (
                  <p className="text-xs text-yellow-700 mt-2.5">
                    Couldn't find {photo.analysis.unmatched.length} item
                    {photo.analysis.unmatched.length > 1 ? "s" : ""} in the food database —
                    add them manually below their dish to count them.
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

// Status colors for a decomposed/custom ingredient.
const ING_STYLE = {
  matched: "bg-green-50 text-green-700",
  unmatched: "bg-yellow-100 text-yellow-700",
  skipped: "bg-gray-200 text-gray-500 line-through",
};

function DishRow({ dish, onDishGrams, onDishRemoved, onIngGrams, onIngRemoved, onAddIngredient }) {
  const removed = dish.removed;
  const decomposed = !dish.matched;
  // Matched dishes scale by an editable dish portion; decomposed dishes derive their grams
  // from the (live) sum of their non-removed ingredients, so the field is read-only there.
  const liveGrams = decomposed
    ? Math.round(
        dish.ingredients.reduce((s, ing) => (ing.removed ? s : s + (ing.grams || 0)), 0)
      )
    : dish.grams;
  // No baseline weight on a matched dish → nothing to scale from, so lock the field.
  const dishLocked = removed || (!decomposed && !(dish.baseGrams > 0));
  const factor = !decomposed && dish.baseGrams > 0 ? (dish.grams || 0) / dish.baseGrams : 1;

  // For a matched dish the detected ingredients were never looked up → read-only chips that
  // scale with the dish portion. Custom adds are always editable rows.
  const chipIngredients = dish.matched ? dish.ingredients.filter((ing) => !ing.custom) : [];
  const rowIngredients = dish.matched
    ? dish.ingredients.filter((ing) => ing.custom)
    : dish.ingredients;

  return (
    <div className={removed ? "opacity-60" : ""}>
      {/* Dish header — a 3-column grid (name | grams | action) so the gram inputs
          and Remove/Undo controls line up in columns across every dish row. */}
      <div className="grid grid-cols-[1fr_auto_auto] items-center gap-2">
        {/* Column 1 — dish name pill + match-status label (absorbs variable width) */}
        <div className="flex items-center gap-1.5 min-w-0">
          <span
            className={`text-xs px-2 py-1 rounded-full font-medium truncate ${
              removed
                ? "bg-gray-100 text-gray-400 line-through"
                : dish.matched ? "bg-green-100 text-green-800" : "bg-white text-gray-700 border border-gray-200"
            }`}
          >
            {dish.name}
          </span>
          {!removed && (dish.matched ? (
            <span className="text-[10px] text-green-700 font-medium shrink-0">matched</span>
          ) : (
            <span className="text-[10px] text-gray-400 shrink-0">from ingredients</span>
          ))}
        </div>
        {/* Column 2 — editable portion (matched) or derived sum (decomposed) */}
        <span className="flex items-center gap-0.5">
          <input
            type="number"
            min="0"
            inputMode="numeric"
            value={Number.isFinite(liveGrams) ? liveGrams : 0}
            onChange={(e) => onDishGrams(e.target.value === "" ? 0 : Math.max(0, Number(e.target.value)))}
            disabled={dishLocked || decomposed}
            title={decomposed ? "Total of the ingredient portions below" : undefined}
            className="w-14 border border-gray-200 rounded-lg px-1.5 py-0.5 text-xs text-right focus:outline-none focus:border-green-400 disabled:bg-gray-100 disabled:text-gray-400"
          />
          <span className="text-[11px] text-gray-400">g</span>
        </span>
        {/* Column 3 — Remove / Undo toggle (whole dish) */}
        {removed ? (
          <span className="flex items-center gap-1.5 justify-self-end">
            <span className="text-[10px] text-gray-400">removed</span>
            <button
              onClick={() => onDishRemoved(false)}
              className="text-[11px] text-green-600 font-medium hover:text-green-700"
            >
              Undo
            </button>
          </span>
        ) : (
          <button
            onClick={() => onDishRemoved(true)}
            className="text-[11px] text-red-400 hover:text-red-500 justify-self-end"
            title="Remove this dish from the meal"
          >
            Remove
          </button>
        )}
      </div>

      {/* Read-only ingredient chips for a matched dish (not individually looked up). */}
      {chipIngredients.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1 pl-3">
          {chipIngredients.map((ing) => {
            const g = Math.round((ing.grams || 0) * factor);
            const style = removed ? "bg-transparent text-gray-400" : "bg-transparent text-gray-500";
            return (
              <span key={ing.id} className={`text-[11px] px-1.5 py-0.5 rounded-full ${style}`}>
                {ing.food}{g > 0 ? ` · ${g}g` : ""}
              </span>
            );
          })}
        </div>
      )}

      {/* Editable ingredient rows: every ingredient of a decomposed dish, plus custom adds. */}
      {rowIngredients.length > 0 && (
        <div className="space-y-1 mt-1.5">
          {rowIngredients.map((ing) => (
            <IngredientRow
              key={ing.id}
              ing={ing}
              locked={removed || !ingHasNutrients(ing)}
              onGrams={(g) => onIngGrams(ing.id, g)}
              onRemove={() => onIngRemoved(ing.id, true)}
              onUndo={() => onIngRemoved(ing.id, false)}
            />
          ))}
        </div>
      )}

      {/* Search USDA foods and add a custom ingredient into this dish. */}
      {!removed && <AddIngredient onAdd={onAddIngredient} />}
    </div>
  );
}

function IngredientRow({ ing, locked, onGrams, onRemove, onUndo }) {
  const removed = ing.removed;
  return (
    <div className={`grid grid-cols-[1fr_auto_auto] items-center gap-2 ${removed ? "opacity-60" : ""}`}>
      <div className="flex items-center gap-1.5 min-w-0 pl-3">
        <span
          className={`text-[11px] px-1.5 py-0.5 rounded-full truncate ${
            removed ? "bg-gray-100 text-gray-400 line-through" : ING_STYLE[ing.status] || "bg-white text-gray-600"
          }`}
        >
          {ing.food}
        </span>
        {!removed && ing.custom && <span className="text-[10px] text-green-600 shrink-0">added</span>}
        {!removed && !ing.custom && ing.status === "unmatched" && (
          <span className="text-[10px] text-yellow-600 shrink-0">not found</span>
        )}
        {!removed && !ing.custom && ing.status === "skipped" && (
          <span className="text-[10px] text-gray-400 shrink-0">over limit</span>
        )}
      </div>
      <span className="flex items-center gap-0.5">
        <input
          type="number"
          min="0"
          inputMode="numeric"
          value={Number.isFinite(ing.grams) ? ing.grams : 0}
          onChange={(e) => onGrams(e.target.value === "" ? 0 : Math.max(0, Number(e.target.value)))}
          disabled={locked}
          className="w-14 border border-gray-200 rounded-lg px-1.5 py-0.5 text-xs text-right focus:outline-none focus:border-green-400 disabled:bg-gray-100 disabled:text-gray-400"
        />
        <span className="text-[11px] text-gray-400">g</span>
      </span>
      {removed ? (
        <span className="flex items-center gap-1.5 justify-self-end">
          <span className="text-[10px] text-gray-400">removed</span>
          <button onClick={onUndo} className="text-[11px] text-green-600 font-medium hover:text-green-700">Undo</button>
        </span>
      ) : (
        <button
          onClick={onRemove}
          className="text-[11px] text-red-400 hover:text-red-500 justify-self-end"
          title="Remove this ingredient"
        >
          Remove
        </button>
      )}
    </div>
  );
}

// Search the offline USDA index and add a chosen food (scaled to the entered grams) as a
// custom ingredient. Type-to-list with a short debounce; a richer keyboard-nav autocomplete
// is deliberately future scope. Falls back gracefully when the offline index isn't built (503).
function AddIngredient({ onAdd }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null); // chosen FoodSummary
  const [grams, setGrams] = useState(100);
  const [adding, setAdding] = useState(false);

  // Debounced search whenever the query changes (and nothing is selected yet).
  useEffect(() => {
    if (!open || selected) return;
    const term = q.trim();
    if (term.length < 2) {
      setResults([]);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const t = setTimeout(async () => {
      try {
        const { data } = await client.get("/foods/search", { params: { q: term, limit: 8 } });
        if (!cancelled) setResults(data);
      } catch (err) {
        if (!cancelled) {
          setResults([]);
          setError(
            err.response?.status === 503
              ? "Food search isn't available (offline index not built)."
              : "Search failed — try again."
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q, open, selected]);

  const reset = () => {
    setOpen(false);
    setQ("");
    setResults([]);
    setSelected(null);
    setGrams(100);
    setError(null);
  };

  const confirmAdd = async () => {
    if (!selected) return;
    setAdding(true);
    setError(null);
    try {
      const { data } = await client.get(`/foods/${selected.fdc_id}`);
      const g = Math.max(0, Number(grams) || 0);
      const scale = g / 100;
      const macros = {};
      for (const k in data.macros) macros[k] = data.macros[k] * scale;
      const micros = {};
      for (const k in data.micros) micros[k] = data.micros[k] * scale;
      onAdd({
        id: uid(),
        food: data.description,
        status: "matched",
        baseGrams: g,
        grams: g,
        macros,
        micros,
        removed: false,
        custom: true,
      });
      reset();
    } catch {
      setError("Couldn't add that food — try again.");
    } finally {
      setAdding(false);
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-[11px] text-green-600 hover:text-green-700 font-medium mt-1.5 pl-3"
      >
        + Add ingredient
      </button>
    );
  }

  return (
    <div className="mt-1.5 pl-3 space-y-1.5">
      <input
        autoFocus
        className="w-full border border-gray-200 rounded-lg px-2 py-1 text-xs focus:outline-none focus:border-green-400"
        placeholder="Search foods (e.g. olive oil)"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setSelected(null);
        }}
      />
      {loading && <p className="text-[11px] text-gray-400">Searching…</p>}
      {error && <p className="text-[11px] text-yellow-600">{error}</p>}
      {!selected && results.length > 0 && (
        <div className="border border-gray-100 rounded-lg divide-y divide-gray-50 max-h-40 overflow-auto bg-white">
          {results.map((f) => (
            <button
              key={f.fdc_id}
              onClick={() => {
                setSelected(f);
                setQ(f.description);
                setResults([]);
              }}
              className="block w-full text-left px-2 py-1 text-[11px] text-gray-700 hover:bg-green-50"
            >
              {f.description}
            </button>
          ))}
        </div>
      )}
      {selected && (
        <div className="flex items-center gap-2">
          <input
            type="number"
            min="0"
            inputMode="numeric"
            value={grams}
            onChange={(e) => setGrams(e.target.value === "" ? 0 : Math.max(0, Number(e.target.value)))}
            className="w-16 border border-gray-200 rounded-lg px-1.5 py-0.5 text-xs text-right focus:outline-none focus:border-green-400"
          />
          <span className="text-[11px] text-gray-400">g</span>
          <button
            onClick={confirmAdd}
            disabled={adding}
            className="text-[11px] bg-green-500 text-white px-2.5 py-1 rounded-lg hover:bg-green-600 disabled:opacity-50"
          >
            {adding ? "Adding…" : "Add"}
          </button>
        </div>
      )}
      <button onClick={reset} className="text-[11px] text-gray-400 hover:text-gray-600 block">
        Close
      </button>
    </div>
  );
}
