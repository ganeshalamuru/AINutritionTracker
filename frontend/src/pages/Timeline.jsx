import { useState, useEffect, useCallback } from "react";
import { useProfile } from "../context/ProfileContext";
import client from "../api/client";
import MealCard from "../components/meal/MealCard";
import Spinner from "../components/shared/Spinner";
import EmptyState from "../components/shared/EmptyState";

function groupByDate(meals) {
  const groups = {};
  for (const m of meals) {
    const d = new Date(m.logged_at).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
    if (!groups[d]) groups[d] = [];
    groups[d].push(m);
  }
  return groups;
}

export default function Timeline() {
  const { profile } = useProfile();
  const [meals, setMeals] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [mealMicros, setMealMicros] = useState({});

  const LIMIT = 20;

  const load = useCallback(async (p = 1) => {
    if (p === 1) setLoading(true); else setLoadingMore(true);
    try {
      const { data } = await client.get(`/meals/timeline?profile_id=${profile.id}&page=${p}&limit=${LIMIT}`);
      setMeals((prev) => p === 1 ? data.items : [...prev, ...data.items]);
      setTotal(data.total);
      setPage(p);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [profile.id]);

  useEffect(() => { load(1); }, [load]);

  const loadMicros = async (mealId) => {
    if (mealMicros[mealId]) return;
    try {
      const { data } = await client.get(`/meals/${mealId}`);
      setMealMicros((prev) => ({ ...prev, [mealId]: data.micros }));
    } catch {}
  };

  const handleDelete = (id) => setMeals((m) => m.filter((x) => x.id !== id));

  if (loading) return <Spinner text="Loading timeline..." />;

  if (!meals.length) {
    return (
      <div className="pt-4">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Meal Timeline</h2>
        <EmptyState icon="📅" title="No meals logged yet" subtitle="Start logging meals to see your history here" />
      </div>
    );
  }

  const groups = groupByDate(meals);

  return (
    <div className="pt-4 space-y-4">
      <h2 className="text-xl font-bold text-gray-900">Meal Timeline</h2>
      {Object.entries(groups).map(([date, dayMeals]) => (
        <div key={date}>
          <h3 className="text-sm font-semibold text-gray-500 mb-2 px-1">{date}</h3>
          <div className="space-y-3">
            {dayMeals.map((m) => {
              if (!mealMicros[m.id]) loadMicros(m.id);
              return (
                <MealCard
                  key={m.id}
                  meal={m}
                  micros={mealMicros[m.id]}
                  onDelete={handleDelete}
                />
              );
            })}
          </div>
        </div>
      ))}
      {meals.length < total && (
        <button
          onClick={() => load(page + 1)}
          disabled={loadingMore}
          className="w-full py-3 text-sm text-green-600 font-medium bg-white rounded-2xl border border-green-200 hover:bg-green-50 disabled:opacity-50"
        >
          {loadingMore ? "Loading..." : `Load more (${total - meals.length} remaining)`}
        </button>
      )}
    </div>
  );
}
