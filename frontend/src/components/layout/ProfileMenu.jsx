import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";

// Avatar button in the TopBar. Opens a dropdown showing the signed-in account with links to
// change the password or log out. (Multi-profile switching was replaced by real accounts —
// switching accounts now means logging out and signing in as someone else.)
export default function ProfileMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const handleLogout = async () => {
    setOpen(false);
    await logout();
    navigate("/login");
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-bold"
        style={{ backgroundColor: user?.avatar_color || "#22c55e" }}
        title="Account"
        aria-label="Account menu"
      >
        {user?.name?.charAt(0).toUpperCase()}
      </button>

      {open && (
        <>
          {/* transparent backdrop closes the menu on outside click */}
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="absolute right-0 mt-2 w-56 bg-white rounded-2xl shadow-xl border border-gray-100 z-30 overflow-hidden">
            <div className="px-4 pt-3 pb-2 flex items-center gap-3">
              <div
                className="w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-bold flex-shrink-0"
                style={{ backgroundColor: user?.avatar_color || "#22c55e" }}
              >
                {user?.name?.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-800 truncate">{user?.name}</p>
                <p className="text-xs text-gray-400 truncate">
                  @{user?.username}
                  {user?.role === "admin" && (
                    <span className="ml-1 text-green-500 font-medium">· admin</span>
                  )}
                </p>
              </div>
            </div>
            <div className="border-t border-gray-100 my-1" />
            <button
              onClick={() => {
                setOpen(false);
                navigate("/change-password");
              }}
              className="w-full px-4 py-2.5 text-left text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Change password
            </button>
            <button
              onClick={handleLogout}
              className="w-full px-4 py-2.5 text-left text-sm font-medium text-red-500 hover:bg-red-50"
            >
              Log out
            </button>
          </div>
        </>
      )}
    </div>
  );
}
