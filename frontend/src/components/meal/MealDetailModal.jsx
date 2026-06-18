import { useState } from "react";
import client from "../../api/client";
import MicroGrid from "./MicroGrid";
import MacroHighlights from "./MacroHighlights";
import FatBreakdown, { hasFatBreakdown, FatCell } from "./FatBreakdown";
import ConfirmModal from "../shared/ConfirmModal";
import { MEAL_TYPE_COLORS } from "../../constants";
import { formatDateTime } from "../../utils/format";

function MacroRow({ nutrients }) {
  const [fatOpen, setFatOpen] = useState(false);
  const fatExpandable = hasFatBreakdown(nutrients);
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-600">Calories</span>
        <span className="font-bold text-gray-900 text-lg">{Math.round(nutrients.calories)} kcal</span>
      </div>
      <MacroHighlights nutrients={nutrients} />
      <div className="grid grid-cols-3 gap-2 text-center text-sm">
        <div className="bg-blue-50 rounded-xl p-2.5">
          <p className="font-bold text-blue-600">{Math.round(nutrients.protein_g)}g</p>
          <p className="text-xs text-gray-500">Protein</p>
        </div>
        <div className="bg-orange-50 rounded-xl p-2.5">
          <p className="font-bold text-orange-500">{Math.round(nutrients.carbs_g)}g</p>
          <p className="text-xs text-gray-500">Carbs</p>
        </div>
        <FatCell
          value={nutrients.fat_g}
          expandable={fatExpandable}
          open={fatOpen}
          onToggle={() => setFatOpen((o) => !o)}
          className="bg-purple-50 rounded-xl p-2.5 w-full"
          valueClass="font-bold text-purple-600"
        />
      </div>
      <FatBreakdown nutrients={nutrients} open={fatOpen} />
      <div className="flex justify-around pt-1 text-xs text-gray-500 border-t border-gray-100">
        <div className="text-center">
          <p className="font-semibold text-gray-700">{Math.round(nutrients.fiber_g)}g</p>
          <p>Fiber</p>
        </div>
        <div className="text-center">
          <p className="font-semibold text-gray-700">{Math.round(nutrients.sugar_g)}g</p>
          <p>Sugar</p>
        </div>
        <div className="text-center">
          <p className="font-semibold text-gray-700">{Math.round(nutrients.sodium_mg)}mg</p>
          <p>Sodium</p>
        </div>
      </div>
    </div>
  );
}

function SingleMealView({ meal, onDelete }) {
  const [deleting, setDeleting] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const time = formatDateTime(meal.logged_at);

  const handleDelete = async () => {
    setConfirming(false);
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
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${MEAL_TYPE_COLORS[meal.meal_type] || "bg-gray-100 text-gray-600"}`}>
              {meal.meal_type}
            </span>
            <span className="text-xs text-gray-400">{time}</span>
          </div>
        </div>
      </div>

      <div className="bg-gray-50 rounded-2xl p-4">
        <MacroRow nutrients={meal.nutrients} />
      </div>

      {meal.nutrients && (
        <div className="bg-gray-50 rounded-2xl p-4">
          <MicroGrid nutrients={meal.nutrients} />
        </div>
      )}

      {meal.notes && (
        <div className="bg-gray-50 rounded-xl p-3">
          <p className="text-xs text-gray-500 mb-1">Notes</p>
          <p className="text-sm text-gray-700">{meal.notes}</p>
        </div>
      )}

      <ConfirmModal
        isOpen={confirming}
        message="Remove this meal?"
        onConfirm={handleDelete}
        onCancel={() => setConfirming(false)}
      />
      <button
        onClick={() => setConfirming(true)}
        disabled={deleting}
        className="w-full py-3 rounded-xl border border-red-200 text-red-500 text-sm font-medium hover:bg-red-50 disabled:opacity-50"
      >
        {deleting ? "Removing..." : "Remove meal"}
      </button>
    </div>
  );
}

function SubMealCard({ sub, isDeleting, onDelete }) {
  const [expanded, setExpanded] = useState(false);
  const [detailNutrients, setDetailNutrients] = useState(null);
  const [loadingMicros, setLoadingMicros] = useState(false);

  const handleToggle = async () => {
    if (expanded) { setExpanded(false); return; }
    setExpanded(true);
    if (detailNutrients) return;
    setLoadingMicros(true);
    try {
      const { data } = await client.get(`/meals/${sub.id}`);
      setDetailNutrients(data.nutrients);
    } catch {}
    setLoadingMicros(false);
  };

  return (
    <div className="bg-gray-50 rounded-2xl p-4 space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <p className="font-semibold text-gray-800 text-sm">{sub.meal_name}</p>
          <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${MEAL_TYPE_COLORS[sub.meal_type] || "bg-gray-100 text-gray-600"}`}>
            {sub.meal_type}
          </span>
        </div>
        <button
          onClick={onDelete}
          disabled={isDeleting}
          className="text-xs text-red-400 hover:text-red-500"
        >
          {isDeleting ? "..." : "Remove"}
        </button>
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-gray-600">
        <span className="font-semibold text-gray-800">{Math.round(sub.nutrients.calories)} kcal</span>
        <span><span className="text-blue-500 font-semibold">{Math.round(sub.nutrients.protein_g)}g</span> protein</span>
        <span><span className="text-orange-400 font-semibold">{Math.round(sub.nutrients.carbs_g)}g</span> carbs</span>
        <span><span className="text-purple-500 font-semibold">{Math.round(sub.nutrients.fat_g)}g</span> fat</span>
      </div>
      <button
        onClick={handleToggle}
        className="text-xs text-green-600 font-medium hover:text-green-700"
      >
        {expanded ? "Hide micros ▲" : "Show micros ▼"}
      </button>
      {expanded && (
        loadingMicros
          ? <p className="text-xs text-gray-400 py-1">Loading...</p>
          : detailNutrients && <MicroGrid nutrients={detailNutrients} alwaysOpen />
      )}
    </div>
  );
}

function GroupMealView({ group, onDelete, onClose }) {
  const [activeTab, setActiveTab] = useState("totals");
  const [deleting, setDeleting] = useState(null);
  const [deletingGroup, setDeletingGroup] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState(null);

  const handleDeleteSub = async (mealId) => {
    setPendingConfirm({
      message: "Remove this item?",
      action: async () => {
        setDeleting(mealId);
        try {
          await client.delete(`/meals/${mealId}`);
          onDelete?.(mealId, group.group_id);
        } finally {
          setDeleting(null);
        }
      },
    });
  };

  const handleDeleteGroup = async () => {
    setPendingConfirm({
      message: "Remove entire meal session?",
      confirmLabel: "Remove session",
      action: async () => {
        setDeletingGroup(true);
        try {
          await client.delete(`/meals/group/${group.group_id}`);
          onDelete?.(null, group.group_id);
          onClose?.();
        } finally {
          setDeletingGroup(false);
        }
      },
    });
  };

  const time = formatDateTime(group.logged_at);

  return (
    <div className="space-y-4">
      <ConfirmModal
        isOpen={!!pendingConfirm}
        message={pendingConfirm?.message}
        confirmLabel={pendingConfirm?.confirmLabel || "Remove"}
        onConfirm={() => { const a = pendingConfirm?.action; setPendingConfirm(null); a?.(); }}
        onCancel={() => setPendingConfirm(null)}
      />
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-bold text-gray-900">
            Meal Session · {group.sub_meals.length} items
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">{time}</p>
        </div>
        <button
          onClick={handleDeleteGroup}
          disabled={deletingGroup}
          className="shrink-0 px-3 py-1.5 rounded-xl border border-red-200 text-red-500 text-xs font-medium hover:bg-red-50 disabled:opacity-50"
        >
          {deletingGroup ? "Removing..." : "Remove session"}
        </button>
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
        <>
          <div className="bg-gray-50 rounded-2xl p-4">
            <MacroRow nutrients={group.total_nutrients} />
          </div>
          {group.total_nutrients && (
            <div className="bg-gray-50 rounded-2xl p-4">
              <MicroGrid nutrients={group.total_nutrients} />
            </div>
          )}
        </>
      )}

      {activeTab === "breakdown" && (
        <div className="space-y-3">
          {group.sub_meals.map((sub) => (
            <SubMealCard
              key={sub.id}
              sub={sub}
              isDeleting={deleting === sub.id}
              onDelete={() => handleDeleteSub(sub.id)}
            />
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
            <GroupMealView group={data.group} onDelete={onDelete} onClose={onClose} />
          )}
        </div>
      </div>
    </div>
  );
}
