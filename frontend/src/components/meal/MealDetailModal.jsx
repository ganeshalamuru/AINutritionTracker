import { useState } from "react";
import client from "../../api/client";
import MicroGrid from "./MicroGrid";

const TYPE_COLORS = {
  breakfast: "bg-yellow-100 text-yellow-700",
  lunch: "bg-green-100 text-green-700",
  dinner: "bg-blue-100 text-blue-700",
  snack: "bg-purple-100 text-purple-700",
};

function MacroRow({ macros }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-600">Calories</span>
        <span className="font-bold text-gray-900 text-lg">{Math.round(macros.calories)} kcal</span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center text-sm">
        <div className="bg-blue-50 rounded-xl p-2.5">
          <p className="font-bold text-blue-600">{Math.round(macros.protein_g)}g</p>
          <p className="text-xs text-gray-500">Protein</p>
        </div>
        <div className="bg-orange-50 rounded-xl p-2.5">
          <p className="font-bold text-orange-500">{Math.round(macros.carbs_g)}g</p>
          <p className="text-xs text-gray-500">Carbs</p>
        </div>
        <div className="bg-purple-50 rounded-xl p-2.5">
          <p className="font-bold text-purple-600">{Math.round(macros.fat_g)}g</p>
          <p className="text-xs text-gray-500">Fat</p>
        </div>
      </div>
      <div className="flex justify-around pt-1 text-xs text-gray-500 border-t border-gray-100">
        <div className="text-center">
          <p className="font-semibold text-gray-700">{Math.round(macros.fiber_g)}g</p>
          <p>Fiber</p>
        </div>
        <div className="text-center">
          <p className="font-semibold text-gray-700">{Math.round(macros.sugar_g)}g</p>
          <p>Sugar</p>
        </div>
        <div className="text-center">
          <p className="font-semibold text-gray-700">{Math.round(macros.sodium_mg)}mg</p>
          <p>Sodium</p>
        </div>
      </div>
    </div>
  );
}

function SingleMealView({ meal, onDelete }) {
  const [deleting, setDeleting] = useState(false);

  const time = new Date(meal.logged_at + "Z").toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });

  const handleDelete = async () => {
    if (!confirm("Remove this meal?")) return;
    setDeleting(true);
    try {
      await client.delete(`/meals/${meal.id}`);
      onDelete?.(meal.id);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold text-gray-900">{meal.meal_name}</h2>
          <div className="flex items-center gap-2 mt-1">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${TYPE_COLORS[meal.meal_type] || "bg-gray-100 text-gray-600"}`}>
              {meal.meal_type}
            </span>
            <span className="text-xs text-gray-400">{time}</span>
          </div>
        </div>
      </div>

      <div className="bg-gray-50 rounded-2xl p-4">
        <MacroRow macros={meal.macros} />
      </div>

      {meal.micros && (
        <div className="bg-gray-50 rounded-2xl p-4">
          <MicroGrid micros={meal.micros} />
        </div>
      )}

      {meal.notes && (
        <div className="bg-gray-50 rounded-xl p-3">
          <p className="text-xs text-gray-500 mb-1">Notes</p>
          <p className="text-sm text-gray-700">{meal.notes}</p>
        </div>
      )}

      <button
        onClick={handleDelete}
        disabled={deleting}
        className="w-full py-3 rounded-xl border border-red-200 text-red-500 text-sm font-medium hover:bg-red-50 disabled:opacity-50"
      >
        {deleting ? "Removing..." : "Remove meal"}
      </button>
    </div>
  );
}

function GroupMealView({ group, onDelete }) {
  const [activeTab, setActiveTab] = useState("totals");
  const [deleting, setDeleting] = useState(null);

  const handleDeleteSub = async (mealId) => {
    if (!confirm("Remove this item?")) return;
    setDeleting(mealId);
    try {
      await client.delete(`/meals/${mealId}`);
      onDelete?.(mealId, group.group_id);
    } finally {
      setDeleting(null);
    }
  };

  const time = new Date(group.logged_at + "Z").toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-bold text-gray-900">
          Meal Session · {group.sub_meals.length} items
        </h2>
        <p className="text-xs text-gray-400 mt-0.5">{time}</p>
      </div>

      <div className="flex gap-1 bg-gray-100 rounded-xl p-1">
        {["totals", "breakdown"].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 py-1.5 rounded-lg text-sm font-medium transition-colors capitalize ${
              activeTab === tab ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "totals" && (
        <div className="bg-gray-50 rounded-2xl p-4">
          <MacroRow macros={group.total_macros} />
        </div>
      )}

      {activeTab === "breakdown" && (
        <div className="space-y-3">
          {group.sub_meals.map((sub) => (
            <div key={sub.id} className="bg-gray-50 rounded-2xl p-4">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <p className="font-semibold text-gray-800 text-sm">{sub.meal_name}</p>
                  <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${TYPE_COLORS[sub.meal_type] || "bg-gray-100 text-gray-600"}`}>
                    {sub.meal_type}
                  </span>
                </div>
                <button
                  onClick={() => handleDeleteSub(sub.id)}
                  disabled={deleting === sub.id}
                  className="text-xs text-red-400 hover:text-red-500"
                >
                  {deleting === sub.id ? "..." : "Remove"}
                </button>
              </div>
              <div className="flex gap-3 text-xs text-gray-600">
                <span className="font-semibold text-gray-800">{Math.round(sub.macros.calories)} kcal</span>
                <span><span className="text-blue-500 font-semibold">{Math.round(sub.macros.protein_g)}g</span> protein</span>
                <span><span className="text-orange-400 font-semibold">{Math.round(sub.macros.carbs_g)}g</span> carbs</span>
                <span><span className="text-purple-500 font-semibold">{Math.round(sub.macros.fat_g)}g</span> fat</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function MealDetailModal({ isOpen, onClose, data, onDelete }) {
  if (!isOpen || !data) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="bg-white w-full max-w-lg rounded-t-3xl max-h-[88vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 bg-gray-200 rounded-full" />
        </div>
        <div className="p-6">
          {data.type === "meal" && (
            <SingleMealView meal={data.meal} onDelete={onDelete} />
          )}
          {data.type === "group" && (
            <GroupMealView group={data.group} onDelete={onDelete} />
          )}
        </div>
      </div>
    </div>
  );
}
