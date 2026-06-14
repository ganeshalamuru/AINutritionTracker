// Single source of truth for daily nutrition goals (mirrors utils/macros.js).
// Calories are a per-profile editable goal. Energy-linked goals (protein, carbs,
// fat, fiber, added sugar) scale linearly with the calorie goal; the sodium limit
// and the vitamin/mineral Daily Values (in MicroGrid) are fixed by body needs, not
// energy intake, so they don't scale here.
//
// Baseline at 2000 kcal is a coherent 20% protein / 50% carbs / 30% fat split
// (100 + 250 + 67 g = 2000 kcal exactly).
export const DEFAULT_CALORIE_GOAL = 2000;

const BASE = { protein_g: 100, carbs_g: 250, fat_g: 67, fiber_g: 28, sugar_g: 50 };
const FIXED = { sodium_mg: 2300 };

export function computeGoals(calorieGoal) {
  const kcal = Number(calorieGoal) || DEFAULT_CALORIE_GOAL;
  const scale = kcal / DEFAULT_CALORIE_GOAL;
  const scaled = Object.fromEntries(
    Object.entries(BASE).map(([k, v]) => [k, Math.round(v * scale)])
  );
  return { calories: kcal, ...scaled, ...FIXED };
}
