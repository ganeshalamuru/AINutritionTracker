import { useState } from "react";

// A single API-key settings card: status chip, password input, and save/update button.
// Owns its own input + saving state; the parent supplies the persisted "is set" flag and
// an async onSave(value) that persists the key. `children` renders the descriptive blurb.
export default function ApiKeyCard({
  title,
  active = false,
  isSet,
  setLabel = "Key saved",
  unsetLabel = "Not set",
  placeholder,
  onSave,
  bare = false,
  children,
}) {
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setSaving(true);
    try {
      await onSave(trimmed);
      setValue("");
    } finally {
      setSaving(false);
    }
  };

  const inner = (
    <>
      <h3 className="font-semibold text-gray-800">
        {title} {active && <span className="text-xs text-green-500">(active)</span>}
      </h3>
      <p className="text-xs text-gray-500">{children}</p>
      <div className="flex items-center gap-2">
        <span className={`text-xs px-2 py-1 rounded-full font-medium ${isSet ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}>
          {isSet ? setLabel : unsetLabel}
        </span>
      </div>
      <input
        type="password"
        className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400 font-mono"
        placeholder={placeholder}
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <button
        onClick={handleSave}
        disabled={saving || !value.trim()}
        className="w-full py-2.5 bg-green-500 text-white rounded-xl text-sm font-medium hover:bg-green-600 disabled:opacity-50"
      >
        {saving ? "Saving..." : isSet ? "Update Key" : "Save Key"}
      </button>
    </>
  );

  // `bare` drops the card chrome so the key can nest inside a SettingsSection (itself
  // a card) without double-carding.
  return bare ? (
    <div className="space-y-3">{inner}</div>
  ) : (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4 space-y-3">{inner}</div>
  );
}
