import { useState, useEffect, useCallback } from "react";
import { useProfile } from "../context/ProfileContext";
import client from "../api/client";
import MealCard from "../components/meal/MealCard";
import GroupedMealCard from "../components/meal/GroupedMealCard";
import MealDetailModal from "../components/meal/MealDetailModal";
import Spinner from "../components/shared/Spinner";
import EmptyState from "../components/shared/EmptyState";

function groupByDate(items) {
  const groups = {};
  for (const item of items) {
    const d = new Date(item.logged_at).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
    if (!groups[d]) groups[d] = [];
    groups[d].push(item);
  }
  return groups;
}

export default function Timeline() {
  const { profile } = useProfile();
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [mealDetails, setMealDetails] = useState({});
  const [modalData, setModalData] = useState(null);

  const LIMIT = 20;

  const load = useCallback(async (p = 1) => {
    if (p === 1) setLoading(true); else setLoadingMore(true);
    try {
      const { data } = await client.get(`/meals/timeline?profile_id=${profile.id}&page=${p}&limit=${LIMIT}`);
      setItems((prev) => p === 1 ? data.items : [...prev, ...data.items]);
      setTotal(data.total);
      setPage(p);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [profile.id]);

  useEffect(() => { load(1); }, [load]);

  const openMealModal = async (mealId) => {
    const cached = mealDetails[mealId];
    if (cached) {
      setModalData({ type: "meal", meal: cached });
      return;
    }
    try {
      const { data } = await client.get(`/meals/${mealId}`);
      setMealDetails((prev) => ({ ...prev, [mealId]: data }));
      setModalData({ type: "meal", meal: data });
    } catch {}
  };

  const openGroupModal = (group) => {
    setModalData({ type: "group", group });
  };

  const handleDelete = (mealId, groupId = null) => {
    setItems((prev) => {
      if (!groupId) {
        return prev.filter((item) => item.item_type !== "meal" || item.id !== mealId);
      }
      return prev
        .map((item) => {
          if (item.item_type !== "group" || item.group_id !== groupId) return item;
          const newSubs = item.sub_meals.filter((s) => s.id !== mealId);
          if (!newSubs.length) return null;
          const total = newSubs.reduce(
            (acc, s) => ({
              calories: acc.calories + s.macros.calories,
              protein_g: acc.protein_g + s.macros.protein_g,
              carbs_g: acc.carbs_g + s.macros.carbs_g,
              fat_g: acc.fat_g + s.macros.fat_g,
              fiber_g: acc.fiber_g + s.macros.fiber_g,
              sugar_g: acc.sugar_g + s.macros.sugar_g,
              sodium_mg: acc.sodium_mg + s.macros.sodium_mg,
            }),
            { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0, sugar_g: 0, sodium_mg: 0 }
          );
          return { ...item, sub_meals: newSubs, total_macros: total };
        })
        .filter(Boolean);
    });
    setModalData(null);
  };

  if (loading) return <Spinner text="Loading timeline..." />;

  if (!items.length) {
    return (
      <div className="pt-4">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Meal Timeline</h2>
        <EmptyState icon="📅" title="No meals logged yet" subtitle="Start logging meals to see your history here" />
      </div>
    );
  }

  const dateGroups = groupByDate(items);

  return (
    <div className="pt-4 space-y-4">
      <h2 className="text-xl font-bold text-gray-900">Meal Timeline</h2>
      {Object.entries(dateGroups).map(([date, dayItems]) => (
        <div key={date}>
          <h3 className="text-sm font-semibold text-gray-500 mb-2 px-1">{date}</h3>
          <div className="space-y-3">
            {dayItems.map((item) =>
              item.item_type === "group" ? (
                <GroupedMealCard
                  key={item.group_id}
                  group={item}
                  onOpenDetail={() => openGroupModal(item)}
                />
              ) : (
                <MealCard
                  key={item.id}
                  meal={item}
                  onOpenDetail={() => openMealModal(item.id)}
                  onDelete={(id) => handleDelete(id)}
                />
              )
            )}
          </div>
        </div>
      ))}

      {items.length < total && (
        <button
          onClick={() => load(page + 1)}
          disabled={loadingMore}
          className="w-full py-3 text-sm text-green-600 font-medium bg-white rounded-2xl border border-green-200 hover:bg-green-50 disabled:opacity-50"
        >
          {loadingMore ? "Loading..." : `Load more (${total - items.length} remaining)`}
        </button>
      )}

      <MealDetailModal
        isOpen={!!modalData}
        onClose={() => setModalData(null)}
        data={modalData}
        onDelete={handleDelete}
      />
    </div>
  );
}
