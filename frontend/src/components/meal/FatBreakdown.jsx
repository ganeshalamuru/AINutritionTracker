import { useState } from "react";

// Label-style breakdown of the meal's total fat — the nutrition-label convention of
// "Total Fat -> of which saturated / mono / poly", plus omega-3 and cholesterol.
// These are stored as micros (display-only) but shown here under Fat rather than in
// MicroGrid. Saturated fat and cholesterol carry FDA Daily Values (so they get a %DV
// bar like MicroGrid); mono/poly/omega-3 have no official DV and show value-only.
// Omega-3 is stored in grams (EPA+DHA) but shown in mg, the readable unit at meal scale.
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

export default function FatBreakdown({ micros }) {
  const [open, setOpen] = useState(false);
  if (!micros) return null;

  const present = ITEMS.map((item) => {
    const raw = Number(micros[item.key]) || 0;
    return { ...item, value: raw * (item.scale || 1), pct: pctDv(raw, item.dv && item.dv) };
  }).filter((i) => i.value > 0);
  if (!present.length) return null;

  return (
    <div className="pt-1">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs text-gray-500 font-medium"
      >
        <span>Fat breakdown</span>
        <svg xmlns="http://www.w3.org/2000/svg" className={`w-3.5 h-3.5 transition-transform ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
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
      )}
    </div>
  );
}
