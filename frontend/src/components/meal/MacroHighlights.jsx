import { useProfile } from "../../context/ProfileContext";
import { computeGoals } from "../../utils/goals";

// Macro headline: what a meal is a high source of, by % of daily goal/limit.
// Mirrors MicroGrid's "Rich in" idea, but splits the framing: protein/carbs/fat/
// fiber are good to hit (green "Rich in"), sugar/sodium are limits to watch
// (amber "High in"). Display-only — goals come from the active profile's calorie
// goal (energy-linked goals scale; the sodium limit is fixed). See utils/goals.js.
const GOOD = [
  { key: "protein_g", label: "Protein", goalKey: "protein_g" },
  { key: "fiber_g", label: "Fiber", goalKey: "fiber_g" },
];
const CAUTION = [
  { key: "carbs_g", label: "Carbs", goalKey: "carbs_g" },
  { key: "fat_g", label: "Fat", goalKey: "fat_g" },
  { key: "sugar_g", label: "Sugar", goalKey: "sugar_g" },
  { key: "sodium_mg", label: "Sodium", goalKey: "sodium_mg" },
];

const RICH = 20; // % of daily goal -> green "Rich in"
const HIGH = 30; // % of daily limit -> amber "High in" (above 20% so a normal
                 // single-meal share, ~33% of 3/day, isn't constantly flagged)

const pct = (value, goal) => (goal ? (Number(value) / goal) * 100 : 0);

function qualifying(items, nutrients, goals, threshold) {
  return items
    .map((m) => ({ ...m, pct: pct(nutrients[m.key], goals[m.goalKey]) }))
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

export default function MacroHighlights({ nutrients }) {
  const { profile } = useProfile();
  if (!nutrients) return null;
  const goals = computeGoals(profile?.calorie_goal);
  const rich = qualifying(GOOD, nutrients, goals, RICH);
  const high = qualifying(CAUTION, nutrients, goals, HIGH);
  if (!rich.length && !high.length) return null;
  return (
    <div className="space-y-1.5">
      <ChipRow icon="★" title="Rich in" items={rich} labelClass="text-gray-500" chipClass="bg-green-100 text-green-700" />
      <ChipRow icon="⚠" title="High in" items={high} labelClass="text-amber-600" chipClass="bg-amber-100 text-amber-700" />
    </div>
  );
}
