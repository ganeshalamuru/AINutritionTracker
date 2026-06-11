import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useProfile } from "../context/ProfileContext";
import client from "../api/client";
import MacroRing from "../components/meal/MacroRing";
import MacroProgressBar from "../components/summary/MacroProgressBar";
import Spinner from "../components/shared/Spinner";
import EmptyState from "../components/shared/EmptyState";
import MealCard from "../components/meal/MealCard";
import GroupedMealCard from "../components/meal/GroupedMealCard";
import MealDetailModal from "../components/meal/MealDetailModal";

function buildDisplayItems(meals) {
  const items = [];
  const groupMap = {};

  for (const meal of meals) {
    if (meal.group_id) {
      if (!groupMap[meal.group_id]) {
        const group = {
          item_type: "group",
          group_id: meal.group_id,
          logged_at: meal.logged_at,
          sub_meals: [],
          total_macros: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0, sugar_g: 0, sodium_mg: 0 },
        };
        groupMap[meal.group_id] = group;
        items.push(group);
      }
      const g = groupMap[meal.group_id];
      g.sub_meals.push({
        id: meal.id,
        meal_name: meal.meal_name,
        meal_type: meal.meal_type,
        logged_at: meal.logged_at,
        macros: {
          calories: meal.calories, protein_g: meal.protein_g, carbs_g: meal.carbs_g,
          fat_g: meal.fat_g, fiber_g: meal.fiber_g, sugar_g: meal.sugar_g, sodium_mg: meal.sodium_mg,
        },
      });
      const t = g.total_macros;
      g.total_macros = {
        calories: t.calories + meal.calories,
        protein_g: t.protein_g + meal.protein_g,
        carbs_g: t.carbs_g + meal.carbs_g,
        fat_g: t.fat_g + meal.fat_g,
        fiber_g: t.fiber_g + (meal.fiber_g || 0),
        sugar_g: t.sugar_g + (meal.sugar_g || 0),
        sodium_mg: t.sodium_mg + (meal.sodium_mg || 0),
      };
    } else {
      items.push({ item_type: "meal", ...meal });
    }
  }
  return items;
}

export default function Home() {
  const { profile } = useProfile();
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [mealDetails, setMealDetails] = useState({});
  const [groupDetails, setGroupDetails] = useState({});
  const [modalData, setModalData] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const now = new Date();
      const localMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const localNextMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
      const { data } = await client.get("/nutrition/daily", {
        params: {
          profile_id: profile.id,
          date_from: localMidnight.toISOString(),
          date_to: localNextMidnight.toISOString(),
        },
      });
      setSummary(data);
    } catch {
      setSummary(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [profile.id]);

  const openMealModal = async (mealId) => {
    const cached = mealDetails[mealId];
    if (cached) { setModalData({ type: "meal", meal: cached }); return; }
    try {
      const { data } = await client.get(`/meals/${mealId}`);
      setMealDetails((prev) => ({ ...prev, [mealId]: data }));
      setModalData({ type: "meal", meal: data });
    } catch {}
  };

  const openGroupModal = async (group) => {
    const cached = groupDetails[group.group_id];
    if (cached) { setModalData({ type: "group", group: cached }); return; }
    try {
      const { data } = await client.get(`/meals/group/${group.group_id}`);
      setGroupDetails((prev) => ({ ...prev, [group.group_id]: data }));
      setModalData({ type: "group", group: data });
    } catch {
      setModalData({ type: "group", group });
    }
  };

  const handleDelete = (mealId, groupId = null) => {
    if (groupId) {
      setGroupDetails((prev) => { const n = { ...prev }; delete n[groupId]; return n; });
    }
    setSummary((s) => {
      if (!s) return s;
      const newMeals = groupId
        ? s.meals.filter((m) => m.group_id !== groupId)
        : s.meals.filter((m) => m.id !== mealId);
      return { ...s, meals: newMeals, meal_count: newMeals.length };
    });
    setModalData(null);
    load();
  };

  if (loading) return <Spinner text="Loading today's summary..." />;

  const totals = summary?.totals || {};
  const displayItems = buildDisplayItems(summary?.meals || []);

  return (
    <div className="pt-4 space-y-4">
      <div>
        <h2 className="text-xl font-bold text-gray-900">Today's Summary</h2>
        <p className="text-sm text-gray-500">{summary?.meal_count || 0} meal{summary?.meal_count !== 1 ? "s" : ""} logged</p>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4">
        <div className="flex items-center justify-center mb-4">
          <MacroRing calories={totals.calories || 0} goal={2000} />
        </div>
        <div className="space-y-3">
          <MacroProgressBar label="Protein" value={totals.protein_g || 0} type="protein" />
          <MacroProgressBar label="Carbs" value={totals.carbs_g || 0} type="carbs" />
          <MacroProgressBar label="Fat" value={totals.fat_g || 0} type="fat" />
        </div>
        <div className="flex justify-around mt-4 pt-4 border-t border-gray-50 text-xs text-gray-500">
          <div className="text-center">
            <p className="font-semibold text-gray-700">{Math.round(totals.fiber_g || 0)}g</p>
            <p>Fiber</p>
          </div>
          <div className="text-center">
            <p className="font-semibold text-gray-700">{Math.round(totals.sugar_g || 0)}g</p>
            <p>Sugar</p>
          </div>
          <div className="text-center">
            <p className="font-semibold text-gray-700">{Math.round(totals.sodium_mg || 0)}mg</p>
            <p>Sodium</p>
          </div>
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold text-gray-800">Today's Meals</h3>
          {(summary?.meals?.length || 0) > 2 && (
            <button onClick={() => navigate("/timeline")} className="text-xs text-green-600 font-medium">See all</button>
          )}
        </div>

        {!displayItems.length ? (
          <EmptyState
            icon="🍽️"
            title="No meals yet today"
            subtitle="Tap the camera button to log your first meal"
            action={
              <button
                onClick={() => navigate("/log")}
                className="bg-green-500 text-white px-6 py-2.5 rounded-xl text-sm font-medium hover:bg-green-600"
              >
                Log a meal
              </button>
            }
          />
        ) : (
          <div className="space-y-3">
            {displayItems.map((item) =>
              item.item_type === "group" ? (
                <GroupedMealCard
                  key={item.group_id}
                  group={item}
                  onOpenDetail={() => openGroupModal(item)}
                  onDelete={handleDelete}
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
        )}
      </div>

      <MealDetailModal
        isOpen={!!modalData}
        onClose={() => setModalData(null)}
        data={modalData}
        onDelete={handleDelete}
      />
    </div>
  );
}
