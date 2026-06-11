export default function MacroRing({ calories, goal = 2000 }) {
  const pct = Math.min((calories / goal) * 100, 100);
  const r = 54;
  const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;

  return (
    <div className="flex flex-col items-center">
      <div className="relative w-36 h-36">
        <svg className="w-full h-full -rotate-90" viewBox="0 0 120 120">
          <circle cx="60" cy="60" r={r} fill="none" stroke="#e5e7eb" strokeWidth="10" />
          <circle
            cx="60" cy="60" r={r} fill="none"
            stroke="#22c55e" strokeWidth="10"
            strokeDasharray={`${dash} ${circ}`}
            strokeLinecap="round"
            className="transition-all duration-700"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-bold text-gray-900">{Math.round(calories)}</span>
          <span className="text-xs text-gray-500">/ {goal} kcal</span>
        </div>
      </div>
      <p className="text-xs text-gray-500 mt-1">Calories</p>
    </div>
  );
}
