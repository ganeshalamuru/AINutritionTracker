import { useState } from "react";

const VITAMINS = [
  { key: "vitamin_a_mcg", label: "Vit A", unit: "mcg" },
  { key: "vitamin_d_mcg", label: "Vit D", unit: "mcg" },
  { key: "vitamin_e_mg", label: "Vit E", unit: "mg" },
  { key: "vitamin_k_mcg", label: "Vit K", unit: "mcg" },
  { key: "vitamin_c_mg", label: "Vit C", unit: "mg" },
  { key: "vitamin_b1_mg", label: "B1", unit: "mg" },
  { key: "vitamin_b2_mg", label: "B2", unit: "mg" },
  { key: "vitamin_b3_mg", label: "B3", unit: "mg" },
  { key: "vitamin_b6_mg", label: "B6", unit: "mg" },
  { key: "vitamin_b12_mcg", label: "B12", unit: "mcg" },
  { key: "folate_mcg", label: "Folate", unit: "mcg" },
];

const MINERALS = [
  { key: "calcium_mg", label: "Calcium", unit: "mg" },
  { key: "iron_mg", label: "Iron", unit: "mg" },
  { key: "magnesium_mg", label: "Magnesium", unit: "mg" },
  { key: "potassium_mg", label: "Potassium", unit: "mg" },
  { key: "zinc_mg", label: "Zinc", unit: "mg" },
  { key: "phosphorus_mg", label: "Phosphorus", unit: "mg" },
];

function Section({ title, items, data }) {
  return (
    <div>
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{title}</p>
      <div className="grid grid-cols-3 gap-2">
        {items.map(({ key, label, unit }) => (
          <div key={key} className="bg-gray-50 rounded-xl p-2 text-center">
            <p className="text-xs font-semibold text-gray-700">{Math.round((data?.[key] || 0) * 10) / 10}<span className="font-normal text-gray-400">{unit}</span></p>
            <p className="text-xs text-gray-500 mt-0.5">{label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function MicroGrid({ micros }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-sm text-gray-600 font-medium"
      >
        <span>Micronutrients</span>
        <svg xmlns="http://www.w3.org/2000/svg" className={`w-4 h-4 transition-transform ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="mt-3 space-y-4">
          <Section title="Vitamins" items={VITAMINS} data={micros} />
          <Section title="Minerals" items={MINERALS} data={micros} />
        </div>
      )}
    </div>
  );
}
