// Badge classes per meal type, shared by meal cards and the detail modal. Callers fall
// back to a neutral gray for unknown types: MEAL_TYPE_COLORS[t] || "bg-gray-100 text-gray-600".
export const MEAL_TYPE_COLORS = {
  breakfast: "bg-yellow-100 text-yellow-700",
  lunch: "bg-green-100 text-green-700",
  dinner: "bg-blue-100 text-blue-700",
  snack: "bg-purple-100 text-purple-700",
};
