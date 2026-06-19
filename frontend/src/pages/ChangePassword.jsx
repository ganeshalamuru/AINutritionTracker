import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import client from "../api/client";

// Used in two ways: forced when the account has must_change_password (migrated PIN accounts,
// or an admin-reset password), and voluntarily from Settings. On success the backend revokes
// all refresh tokens, so we immediately re-authenticate with the new password to get a fresh
// session rather than bouncing the user to the login screen.
export default function ChangePassword() {
  const { user, login, logout } = useAuth();
  const navigate = useNavigate();
  const forced = !!user?.must_change_password;
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (next.length < 8) {
      setError("New password must be at least 8 characters");
      return;
    }
    if (next !== confirm) {
      setError("New passwords don't match");
      return;
    }
    setBusy(true);
    try {
      await client.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      // Sessions were revoked server-side — re-login with the new password for a fresh pair.
      await login(user.username, next);
      navigate("/home");
    } catch (err) {
      setError(err.response?.status === 400 ? "Current password is incorrect" : "Could not change password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center px-4 py-8">
      <div className="w-full max-w-sm">
        <div className="text-center mb-6">
          <div className="text-4xl mb-2">🔒</div>
          <h1 className="text-xl font-bold text-gray-900">
            {forced ? "Set a new password" : "Change password"}
          </h1>
          {forced && (
            <p className="text-sm text-gray-500 mt-1">
              Your account is using a temporary password. Choose a new one to continue.
            </p>
          )}
        </div>

        <form onSubmit={handleSubmit} className="bg-white rounded-3xl shadow-sm p-6 space-y-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">
              {forced ? "Temporary password" : "Current password"}
            </label>
            <input
              type="password"
              autoComplete="current-password"
              className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">New password</label>
            <input
              type="password"
              autoComplete="new-password"
              className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400"
              placeholder="At least 8 characters"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Confirm new password</label>
            <input
              type="password"
              autoComplete="new-password"
              className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-green-400"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
          </div>

          {error && <p className="text-sm text-red-500 text-center">{error}</p>}

          <button
            type="submit"
            disabled={busy}
            className="w-full py-2.5 rounded-xl bg-green-500 text-white text-sm font-medium hover:bg-green-600 disabled:opacity-50"
          >
            {busy ? "Saving..." : "Save password"}
          </button>
          {!forced && (
            <button
              type="button"
              onClick={() => navigate("/settings")}
              className="w-full py-2.5 rounded-xl border border-gray-200 text-sm text-gray-600 hover:bg-gray-50"
            >
              Cancel
            </button>
          )}
          {forced && (
            <button
              type="button"
              onClick={async () => {
                await logout();
                navigate("/login");
              }}
              className="w-full text-xs text-gray-400 hover:text-gray-600"
            >
              Sign out instead
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
