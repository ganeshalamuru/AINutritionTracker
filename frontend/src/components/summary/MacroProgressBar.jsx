const COLORS = { protein: "#3b82f6", carbs: "#f97316", fat: "#a855f7" };
const GOALS = { protein: 150, carbs: 250, fat: 65 };

export default function MacroProgressBar({ label, value, unit = "g", type }) {
  const goal = GOALS[type] || 100;
  const pct = Math.min((value / goal) * 100, 100);
  const color = COLORS[type] || "#22c55e";

  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-xs text-gray-600">
        <span className="font-medium capitalize">{label}</span>
        <span>{Math.round(value)}{unit} <span className="text-gray-400">/ {goal}{unit}</span></span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}
