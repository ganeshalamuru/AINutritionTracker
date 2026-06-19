// The headline macro fields every meal/group total carries, in display order. Centralized
// so the empty-seed helper stays in sync wherever totals are assembled — seeding these
// keys to 0 guarantees cards always render the headline macros even before any are summed.
export const MACRO_KEYS = [
  "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg",
];

// A zeroed accumulator seeded with the headline macro keys, ready to sum into.
export const emptyNutrients = () => Object.fromEntries(MACRO_KEYS.map((k) => [k, 0]));

// Add one meal's flat nutrient object into an accumulator in place, summing every key
// present (macros + micros + fat breakdown); the backend ships one "standard nutrients"
// bag, so this covers whatever the payload carries. Missing acc keys count as 0.
export const addNutrients = (acc, n) => {
  for (const k in n || {}) acc[k] = (acc[k] || 0) + (Number(n[k]) || 0);
  return acc;
};
