// Label-style breakdown of the meal's total fat — the nutrition-label convention of
// "Total Fat -> of which saturated / mono / poly", plus omega-3 and cholesterol.
// These are stored as micros (display-only) but shown here under Fat rather than in
// MicroGrid. Saturated fat and cholesterol carry FDA Daily Values (so they get a %DV
// bar like MicroGrid); mono/poly/omega-3 have no official DV and show value-only.
// Omega-3 is stored in grams (EPA+DHA) but shown in mg, the readable unit at meal scale.
//
// This renders only the breakdown panel; the expand/collapse toggle lives on the Fat
// macro cell in the parent. Use hasFatBreakdown(micros) to decide whether that cell
// should be tappable.
const ITEMS = [
  { key: "saturated_fat_g", label: "Saturated", unit: "g", dv: 20 },
  { key: "mono_fat_g", label: "Monounsaturated", unit: "g", dv: null },
  { key: "poly_fat_g", label: "Polyunsaturated", unit: "g", dv: null },
  { key: "omega3_g", label: "Omega-3 (EPA+DHA)", unit: "mg", dv: null, scale: 1000 },
  { key: "cholesterol_mg", label: "Cholesterol", unit: "mg", dv: 300 },
];

const round1 = (n) => Math.round((n || 0) * 10) / 10;
const pctDv = (value, dv) => (dv ? (Number(value) / dv) * 100 : 0);

// FDA labeling thresholds, mirroring MicroGrid.
function dvColor(pct) {
  if (pct >= 20) return "#22c55e"; // green-500
  if (pct >= 10) return "#86efac"; // green-300
  return "#d1d5db"; // gray-300
}

// Items present (value > 0) for the given micros, with display value and %DV computed.
function presentItems(micros) {
  if (!micros) return [];
  return ITEMS.map((item) => {
    const raw = Number(micros[item.key]) || 0;
    return { ...item, value: raw * (item.scale || 1), pct: pctDv(raw, item.dv && item.dv) };
  }).filter((i) => i.value > 0);
}

// Whether there's any fat breakdown to show — drives the tappable Fat cell in parents.
export function hasFatBreakdown(micros) {
  return presentItems(micros).length > 0;
}

// The Fat macro cell. When expandable it's a button that toggles the breakdown panel,
// showing a chevron that rotates open. Styling is passed in so it can match each screen's
// macro grid (MealDetailModal vs LogMeal review).
export function FatCell({ value, expandable, open, onToggle, className, valueClass, labelClass = "text-xs text-gray-500" }) {
  const inner = (
    <>
      <p className={valueClass}>{Math.round(value || 0)}g</p>
      <p className={`flex items-center justify-center gap-0.5 ${labelClass}`}>
        Fat
        {expandable && (
          <svg xmlns="http://www.w3.org/2000/svg" className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </p>
    </>
  );
  if (!expandable) return <div className={className}>{inner}</div>;
  return (
    <button type="button" onClick={onToggle} aria-expanded={open} className={`${className} ${open ? "ring-1 ring-purple-200" : ""}`}>
      {inner}
    </button>
  );
}

export default function FatBreakdown({ micros, open }) {
  if (!open) return null;
  const present = presentItems(micros);
  if (!present.length) return null;

  return (
    <div className="mt-2 space-y-2">
      {present.map(({ key, label, unit, value, dv, pct }) => (
        <div key={key} className="flex flex-col gap-1">
          <div className="flex justify-between items-baseline text-xs">
            <span className="font-medium text-gray-600">{label}</span>
            <span className="text-gray-500">
              {round1(value)}{unit}
              {dv ? <span className="text-gray-400"> · {Math.round(pct)}%</span> : null}
            </span>
          </div>
          {dv ? (
            <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${Math.min(pct, 100)}%`, backgroundColor: dvColor(pct) }}
              />
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}
