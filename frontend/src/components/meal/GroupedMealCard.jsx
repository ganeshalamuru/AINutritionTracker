import { useState } from "react";
import client from "../../api/client";
import ConfirmModal from "../shared/ConfirmModal";

const TYPE_COLORS = {
  breakfast: "bg-yellow-100 text-yellow-700",
  lunch: "bg-green-100 text-green-700",
  dinner: "bg-blue-100 text-blue-700",
  snack: "bg-purple-100 text-purple-700",
};

export default function GroupedMealCard({ group, onOpenDetail, onDelete }) {
  const [deleting, setDeleting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const time = new Date(group.logged_at + "Z").toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  const t = group.total_macros;

  const mealTypes = [...new Set(group.sub_meals.map((s) => s.meal_type))];

  const handleDelete = async () => {
    setConfirming(false);
    setDeleting(true);
    try {
      await client.delete(`/meals/group/${group.group_id}`);
      onDelete?.(null, group.group_id);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
    <ConfirmModal
      isOpen={confirming}
      message="Remove entire meal session?"
      confirmLabel="Remove session"
      onConfirm={handleDelete}
      onCancel={() => setConfirming(false)}
    />
    <div
      className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4 cursor-pointer hover:shadow-md transition-shadow active:scale-[0.99]"
      onClick={onOpenDetail}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            {mealTypes.map((type) => (
              <span
                key={type}
                className={`text-xs px-2 py-0.5 rounded-full font-medium ${TYPE_COLORS[type] || "bg-gray-100 text-gray-600"}`}
              >
                {type}
              </span>
            ))}
            <span className="text-xs text-gray-400">{time}</span>
          </div>
          <p className="font-semibold text-gray-900 text-sm truncate">
            {group.sub_meals.map((s) => s.meal_name).join(", ")}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">{group.sub_meals.length} items</p>
        </div>
        <div className="text-right flex-shrink-0">
          <p className="font-bold text-gray-900">{Math.round(t.calories)}</p>
          <p className="text-xs text-gray-500">kcal</p>
        </div>
      </div>

      <div className="flex gap-3 text-xs text-gray-600">
        <span><span className="text-blue-500 font-semibold">{Math.round(t.protein_g)}g</span> protein</span>
        <span><span className="text-orange-400 font-semibold">{Math.round(t.carbs_g)}g</span> carbs</span>
        <span><span className="text-purple-500 font-semibold">{Math.round(t.fat_g)}g</span> fat</span>
      </div>

      <div className="flex gap-4 mt-2 text-xs text-gray-400">
        <span>Fiber {Math.round(t.fiber_g)}g</span>
        <span>Sugar {Math.round(t.sugar_g)}g</span>
        <span>Sodium {Math.round(t.sodium_mg)}mg</span>
      </div>

      <div className="flex items-center justify-between mt-3">
        <span className="text-xs text-green-600 font-medium">Tap to view details →</span>
        <button
          onClick={(e) => { e.stopPropagation(); setConfirming(true); }}
          disabled={deleting}
          className="text-xs text-red-400 hover:text-red-500"
        >
          {deleting ? "..." : "Remove"}
        </button>
      </div>
    </div>
    </>
  );
}
