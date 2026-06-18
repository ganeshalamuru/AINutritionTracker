// The macro fields every meal/group total carries, in display order. Centralized so
// the empty-seed and summation helpers stay in sync wherever totals are assembled.
export const MACRO_KEYS = [
  "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg",
];

// A zeroed macro object to seed an accumulation.
export const emptyMacros = () => Object.fromEntries(MACRO_KEYS.map((k) => [k, 0]));

// Add one meal's macros into an accumulator in place; missing fields count as 0.
export const addMacros = (acc, m) => {
  for (const k of MACRO_KEYS) acc[k] += m[k] || 0;
  return acc;
};

// Add one meal's full flat nutrient object into an accumulator in place, summing every
// key present (macros + micros + fat breakdown) — the backend ships one "standard
// nutrients" bag, so client-side group recompute covers all of it, not just macros.
export const addNutrients = (acc, n) => {
  for (const k in n || {}) acc[k] = (acc[k] || 0) + (Number(n[k]) || 0);
  return acc;
};
