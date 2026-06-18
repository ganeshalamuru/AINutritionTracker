import { useState } from "react";

// Full micro label set with FDA adult Daily Values (DV). The AI reports only the
// micros notable for a given meal, so we render just the ones with a value and sort
// them by % of Daily Value so the meal's standout nutrients surface first.
const VITAMINS = [
  { key: "vitamin_a_mcg", label: "Vitamin A", unit: "mcg", dv: 900 },
  { key: "vitamin_d_mcg", label: "Vitamin D", unit: "mcg", dv: 20 },
  { key: "vitamin_e_mg", label: "Vitamin E", unit: "mg", dv: 15 },
  { key: "vitamin_k_mcg", label: "Vitamin K", unit: "mcg", dv: 120 },
  { key: "vitamin_c_mg", label: "Vitamin C", unit: "mg", dv: 90 },
  { key: "vitamin_b1_mg", label: "Thiamin (B1)", unit: "mg", dv: 1.2 },
  { key: "vitamin_b2_mg", label: "Riboflavin (B2)", unit: "mg", dv: 1.3 },
  { key: "vitamin_b3_mg", label: "Niacin (B3)", unit: "mg", dv: 16 },
  { key: "vitamin_b6_mg", label: "Vitamin B6", unit: "mg", dv: 1.7 },
  { key: "vitamin_b12_mcg", label: "Vitamin B12", unit: "mcg", dv: 2.4 },
  { key: "folate_mcg", label: "Folate", unit: "mcg", dv: 400 },
];

const MINERALS = [
  { key: "calcium_mg", label: "Calcium", unit: "mg", dv: 1300 },
  { key: "iron_mg", label: "Iron", unit: "mg", dv: 18 },
  { key: "magnesium_mg", label: "Magnesium", unit: "mg", dv: 420 },
  { key: "potassium_mg", label: "Potassium", unit: "mg", dv: 4700 },
  { key: "zinc_mg", label: "Zinc", unit: "mg", dv: 11 },
  { key: "phosphorus_mg", label: "Phosphorus", unit: "mg", dv: 1250 },
  { key: "selenium_mcg", label: "Selenium", unit: "mcg", dv: 55 },
  { key: "copper_mg", label: "Copper", unit: "mg", dv: 0.9 },
];

// Choline has an FDA DV; caffeine has none, so it renders value-only (pct 0 -> no bar fill).
const OTHER = [
  { key: "choline_mg", label: "Choline", unit: "mg", dv: 550 },
  { key: "caffeine_mg", label: "Caffeine", unit: "mg", dv: null },
];

const round1 = (n) => Math.round((n || 0) * 10) / 10;
const pctDv = (value, dv) => (dv ? (Number(value) / dv) * 100 : 0);

// FDA labeling thresholds: >=20% DV = "high", 10-19% = "good source".
const HIGH = 20;
const GOOD = 10;
function richColor(pct) {
  if (pct >= HIGH) return "#22c55e"; // green-500
  if (pct >= GOOD) return "#86efac"; // green-300
  return "#d1d5db"; // gray-300
}

// Present (non-zero) items for a list, each with its %DV, sorted richest first.
function presentItems(items, data) {
  return items
    .filter(({ key }) => Number(data?.[key]) > 0)
    .map((item) => ({ ...item, value: Number(data[item.key]), pct: pctDv(data[item.key], item.dv) }))
    .sort((a, b) => b.pct - a.pct);
}

function Section({ title, items }) {
  if (!items.length) return null;
  return (
    <div>
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{title}</p>
      <div className="space-y-2.5">
        {items.map(({ key, label, unit, value, pct, dv }) => (
          <div key={key} className="flex flex-col gap-1">
            <div className="flex justify-between items-baseline text-sm">
              <span className="font-medium text-gray-700">{label}</span>
              <span className="text-gray-500">
                {round1(value)}{unit}
                {dv ? <span className="text-gray-400"> · {Math.round(pct)}%</span> : null}
              </span>
            </div>
            {dv ? (
              <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(pct, 100)}%`, backgroundColor: richColor(pct) }}
                />
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

// Headline row naming what the meal is a high (or at least good) source of.
function RichIn({ items }) {
  const high = items.filter((i) => i.pct >= HIGH);
  const source = high.length ? high : items.filter((i) => i.pct >= GOOD);
  if (!source.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs font-semibold text-gray-500">
        {high.length ? "★ Rich in" : "Good source of"}
      </span>
      {source.map((i) => (
        <span key={i.key} className="text-xs font-medium px-2 py-0.5 rounded-full bg-green-100 text-green-700">
          {i.label}
        </span>
      ))}
    </div>
  );
}

export default function MicroGrid({ nutrients, alwaysOpen = false }) {
  const [open, setOpen] = useState(false);
  const isOpen = alwaysOpen || open;

  const vitamins = presentItems(VITAMINS, nutrients);
  const minerals = presentItems(MINERALS, nutrients);
  const other = presentItems(OTHER, nutrients);
  const hasAny = vitamins.length > 0 || minerals.length > 0 || other.length > 0;
  // Rich-in spans the DV-bearing groups, still ordered richest first (caffeine has no
  // DV so it never qualifies as "rich in" anyway).
  const allPresent = [...vitamins, ...minerals, ...other].sort((a, b) => b.pct - a.pct);

  return (
    <div className="mt-3">
      {!alwaysOpen && (
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1 text-sm text-gray-600 font-medium"
        >
          <span>Micronutrients</span>
          <svg xmlns="http://www.w3.org/2000/svg" className={`w-4 h-4 transition-transform ${isOpen ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      )}
      {isOpen && (
        <div className="mt-3 space-y-4">
          {hasAny ? (
            <>
              <RichIn items={allPresent} />
              <Section title="Vitamins" items={vitamins} />
              <Section title="Minerals" items={minerals} />
              <Section title="Other" items={other} />
            </>
          ) : (
            <p className="text-xs text-gray-400">No notable micronutrients.</p>
          )}
        </div>
      )}
    </div>
  );
}
