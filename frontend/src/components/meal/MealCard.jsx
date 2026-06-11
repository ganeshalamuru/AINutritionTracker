import { useState } from "react";
import MicroGrid from "./MicroGrid";
import client from "../../api/client";

const TYPE_COLORS = {
  breakfast: "bg-yellow-100 text-yellow-700",
  lunch: "bg-green-100 text-green-700",
  dinner: "bg-blue-100 text-blue-700",
  snack: "bg-purple-100 text-purple-700",
};

export default function MealCard({ meal, micros, onDelete }) {
  const [expanded, setExpanded] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const time = new Date(meal.logged_at).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });

  const handleDelete = async () => {
    if (!confirm("Remove this meal?")) return;
    setDeleting(true);
    await client.delete(`/meals/${meal.id}`);
    onDelete?.(meal.id);
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${TYPE_COLORS[meal.meal_type] || "bg-gray-100 text-gray-600"}`}>
              {meal.meal_type}
            </span>
            <span className="text-xs text-gray-400">{time}</span>
          </div>
          <h3 className="font-semibold text-gray-900 truncate">{meal.meal_name}</h3>
        </div>
        <div className="text-right flex-shrink-0">
          <p className="font-bold text-gray-900">{Math.round(meal.calories)}</p>
          <p className="text-xs text-gray-500">kcal</p>
        </div>
      </div>

      <div className="flex gap-3 mt-2 text-xs text-gray-600">
        <span><span className="text-blue-500 font-semibold">{Math.round(meal.protein_g)}g</span> protein</span>
        <span><span className="text-orange-400 font-semibold">{Math.round(meal.carbs_g)}g</span> carbs</span>
        <span><span className="text-purple-500 font-semibold">{Math.round(meal.fat_g)}g</span> fat</span>
      </div>

      <div className="flex items-center justify-between mt-3">
        <button
          onClick={() => setExpanded((e) => !e)}
          className="text-xs text-green-600 font-medium flex items-center gap-1"
        >
          {expanded ? "Less" : "Micros"}
          <svg xmlns="http://www.w3.org/2000/svg" className={`w-3 h-3 transition-transform ${expanded ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="text-xs text-red-400 hover:text-red-500"
        >
          {deleting ? "..." : "Remove"}
        </button>
      </div>

      {expanded && micros && <MicroGrid micros={micros} />}
    </div>
  );
}
