import { useState } from "react";

export default function PinPad({ onSubmit, onCancel, error }) {
  const [pin, setPin] = useState("");

  const handleKey = (digit) => {
    if (pin.length < 4) {
      const next = pin + digit;
      setPin(next);
      if (next.length === 4) {
        setTimeout(() => onSubmit(next), 100);
        setPin("");
      }
    }
  };

  const handleDelete = () => setPin((p) => p.slice(0, -1));

  return (
    <div className="flex flex-col items-center gap-6 py-4">
      <div className="flex gap-3">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className={`w-4 h-4 rounded-full border-2 transition-all ${
              i < pin.length ? "bg-green-500 border-green-500" : "border-gray-300"
            }`}
          />
        ))}
      </div>
      {error && <p className="text-red-500 text-sm">{error}</p>}
      <div className="grid grid-cols-3 gap-3 w-56">
        {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((d) => (
          <button
            key={d}
            onClick={() => handleKey(String(d))}
            className="h-14 rounded-2xl bg-gray-100 text-xl font-semibold text-gray-800 hover:bg-gray-200 active:scale-95 transition-all"
          >
            {d}
          </button>
        ))}
        <button
          onClick={onCancel}
          className="h-14 rounded-2xl bg-gray-50 text-sm text-gray-500 hover:bg-gray-100 active:scale-95 transition-all"
        >
          Cancel
        </button>
        <button
          onClick={() => handleKey("0")}
          className="h-14 rounded-2xl bg-gray-100 text-xl font-semibold text-gray-800 hover:bg-gray-200 active:scale-95 transition-all"
        >
          0
        </button>
        <button
          onClick={handleDelete}
          className="h-14 rounded-2xl bg-gray-50 text-gray-500 flex items-center justify-center hover:bg-gray-100 active:scale-95 transition-all"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2M3 12l6.414 6.414a2 2 0 001.414.586H19a2 2 0 002-2V7a2 2 0 00-2-2h-8.172a2 2 0 00-1.414.586L3 12z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
