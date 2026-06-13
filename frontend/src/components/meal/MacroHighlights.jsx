// Macro headline: what a meal is a high source of, by % of daily goal/limit.
// Mirrors MicroGrid's "Rich in" idea, but splits the framing: protein/carbs/fat/
// fiber are good to hit (green "Rich in"), sugar/sodium are limits to watch
// (amber "High in"). Display-only — goals live here like MicroGrid's DV table.
const GOOD = [
  { key: "protein_g", label: "Protein", goal: 150 },
  { key: "carbs_g", label: "Carbs", goal: 250 },
  { key: "fat_g", label: "Fat", goal: 65 },
  { key: "fiber_g", label: "Fiber", goal: 28 },
];
const CAUTION = [
  { key: "sugar_g", label: "Sugar", goal: 50 },
  { key: "sodium_mg", label: "Sodium", goal: 2300 },
];

const RICH = 20; // % of daily goal -> green "Rich in"
const HIGH = 30; // % of daily limit -> amber "High in" (above 20% so a normal
                 // single-meal share, ~33% of 3/day, isn't constantly flagged)

const pct = (value, goal) => (goal ? (Number(value) / goal) * 100 : 0);

function qualifying(items, macros, threshold) {
  return items
    .map((m) => ({ ...m, pct: pct(macros[m.key], m.goal) }))
    .filter((m) => m.pct >= threshold)
    .sort((a, b) => b.pct - a.pct);
}

function ChipRow({ icon, title, items, labelClass, chipClass }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className={`text-xs font-semibold ${labelClass}`}>{icon} {title}</span>
      {items.map((m) => (
        <span key={m.key} className={`text-xs font-medium px-2 py-0.5 rounded-full ${chipClass}`}>
          {m.label}
        </span>
      ))}
    </div>
  );
}

export default function MacroHighlights({ macros }) {
  if (!macros) return null;
  const rich = qualifying(GOOD, macros, RICH);
  const high = qualifying(CAUTION, macros, HIGH);
  if (!rich.length && !high.length) return null;
  return (
    <div className="space-y-1.5">
      <ChipRow icon="★" title="Rich in" items={rich} labelClass="text-gray-500" chipClass="bg-green-100 text-green-700" />
      <ChipRow icon="⚠" title="High in" items={high} labelClass="text-amber-600" chipClass="bg-amber-100 text-amber-700" />
    </div>
  );
}
