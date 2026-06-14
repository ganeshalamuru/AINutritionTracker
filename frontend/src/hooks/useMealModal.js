import { useState } from "react";
import client from "../api/client";

// Shared meal-detail modal state for Home and Timeline. Holds the open modal payload and
// a per-meal detail cache (single meals carry micros only fetched on demand). Opening the
// same meal twice reuses the cached detail instead of re-fetching.
//
// Group modals stay page-specific: Home fetches/caches full group detail, Timeline opens
// the in-memory group as-is — so this hook covers single meals + modal state only, and each
// page wires its own openGroup via setModalData.
export function useMealModal() {
  const [modalData, setModalData] = useState(null);
  const [mealDetails, setMealDetails] = useState({});

  const openMeal = async (mealId) => {
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

  const closeModal = () => setModalData(null);

  return { modalData, setModalData, openMeal, closeModal };
}
