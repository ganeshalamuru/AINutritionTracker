import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useProfile } from "../context/ProfileContext";
import client from "../api/client";
import MacroRing from "../components/meal/MacroRing";
import MacroProgressBar from "../components/summary/MacroProgressBar";
import Spinner from "../components/shared/Spinner";
import EmptyState from "../components/shared/EmptyState";
import MealCard from "../components/meal/MealCard";

export default function Home() {
  const { profile } = useProfile();
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [mealMicros, setMealMicros] = useState({});

  const today = new Date().toISOString().slice(0, 10);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await client.get(`/nutrition/daily?profile_id=${profile.id}&date=${today}`);
      setSummary(data);
    } catch {
      setSummary(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [profile.id]);

  const loadMicros = async (mealId) => {
    if (mealMicros[mealId]) return;
    try {
      const { data } = await client.get(`/meals/${mealId}`);
      setMealMicros((prev) => ({ ...prev, [mealId]: data.micros }));
    } catch {}
  };

  const handleDelete = (id) => {
    setSummary((s) => s ? { ...s, meals: s.meals.filter((m) => m.id !== id), meal_count: s.meal_count - 1 } : s);
    load();
  };

  if (loading) return <Spinner text="Loading today's summary..." />;

  const totals = summary?.totals || {};

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

        {!summary?.meals?.length ? (
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
            {summary.meals.map((m) => {
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
        )}
      </div>
    </div>
  );
}
