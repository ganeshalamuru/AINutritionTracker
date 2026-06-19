import { useState, useEffect } from "react";
import { useAuth } from "../context/AuthContext";
import client from "../api/client";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import Spinner from "../components/shared/Spinner";
import EmptyState from "../components/shared/EmptyState";

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function Monthly() {
  const { user } = useAuth();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    client.get(`/nutrition/monthly?year=${year}&month=${month}`)
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [user.id, year, month]);

  const prevMonth = () => {
    if (month === 1) { setMonth(12); setYear((y) => y - 1); }
    else setMonth((m) => m - 1);
  };
  const nextMonth = () => {
    if (month === 12) { setMonth(1); setYear((y) => y + 1); }
    else setMonth((m) => m + 1);
  };

  const isCurrentOrFuture = year > now.getFullYear() || (year === now.getFullYear() && month >= now.getMonth() + 1);

  return (
    <div className="pt-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-900">Monthly</h2>
        <div className="flex items-center gap-2">
          <button onClick={prevMonth} className="w-8 h-8 flex items-center justify-center rounded-full bg-gray-100 hover:bg-gray-200 text-gray-600">
            <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <span className="text-sm font-semibold text-gray-700 w-20 text-center">{MONTH_NAMES[month - 1]} {year}</span>
          <button onClick={nextMonth} disabled={isCurrentOrFuture} className="w-8 h-8 flex items-center justify-center rounded-full bg-gray-100 hover:bg-gray-200 text-gray-600 disabled:opacity-30">
            <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>
      </div>

      {loading && <Spinner text="Loading monthly data..." />}

      {!loading && (!data || data.days_logged === 0) && (
        <EmptyState icon="📊" title="No data for this month" subtitle="Log some meals to see monthly trends" />
      )}

      {!loading && data && data.days_logged > 0 && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-3 text-center">
              <p className="text-lg font-bold text-gray-900">{data.days_logged}</p>
              <p className="text-xs text-gray-500">Days logged</p>
            </div>
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-3 text-center">
              <p className="text-lg font-bold text-gray-900">{Math.round(data.monthly_averages.calories)}</p>
              <p className="text-xs text-gray-500">Avg kcal/day</p>
            </div>
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-3 text-center">
              <p className="text-lg font-bold text-gray-900">{Math.round(data.monthly_averages.protein_g)}g</p>
              <p className="text-xs text-gray-500">Avg protein</p>
            </div>
          </div>

          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4">
            <h3 className="font-semibold text-gray-800 mb-3">Daily Calories</h3>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={data.daily_breakdown} margin={{ top: 0, right: 0, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: "#9ca3af" }}
                  tickFormatter={(v) => v.slice(8)}
                />
                <YAxis tick={{ fontSize: 10, fill: "#9ca3af" }} />
                <Tooltip
                  formatter={(v) => [`${Math.round(v)} kcal`, "Calories"]}
                  labelFormatter={(l) => new Date(l).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  contentStyle={{ borderRadius: 12, border: "1px solid #e5e7eb", fontSize: 12 }}
                />
                <Bar dataKey="calories" fill="#22c55e" radius={[4, 4, 0, 0]} maxBarSize={20} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4">
            <h3 className="font-semibold text-gray-800 mb-3">Monthly Averages</h3>
            <div className="grid grid-cols-2 gap-3 text-sm">
              {[
                { label: "Protein", value: data.monthly_averages.protein_g, unit: "g", color: "text-blue-500" },
                { label: "Carbs", value: data.monthly_averages.carbs_g, unit: "g", color: "text-orange-400" },
                { label: "Fat", value: data.monthly_averages.fat_g, unit: "g", color: "text-purple-500" },
                { label: "Fiber", value: data.monthly_averages.fiber_g, unit: "g", color: "text-green-500" },
                { label: "Sugar", value: data.monthly_averages.sugar_g, unit: "g", color: "text-red-400" },
                { label: "Sodium", value: data.monthly_averages.sodium_mg, unit: "mg", color: "text-gray-600" },
              ].map(({ label, value, unit, color }) => (
                <div key={label} className="flex justify-between items-center bg-gray-50 rounded-xl px-3 py-2">
                  <span className="text-gray-600 text-xs">{label}</span>
                  <span className={`font-semibold text-sm ${color}`}>{Math.round(value)}{unit}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
