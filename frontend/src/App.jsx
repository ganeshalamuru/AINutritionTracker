import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { LogDraftProvider } from "./context/LogDraftContext";
import Login from "./pages/Login";
import Register from "./pages/Register";
import ChangePassword from "./pages/ChangePassword";
import Home from "./pages/Home";
import LogMeal from "./pages/LogMeal";
import Timeline from "./pages/Timeline";
import Monthly from "./pages/Monthly";
import Settings from "./pages/Settings";
import Layout from "./components/layout/Layout";
import Spinner from "./components/shared/Spinner";

// Gate the app behind a valid session. While the boot refresh is in flight we show a spinner
// instead of flashing the login screen. A migrated/admin-reset account with a temporary
// password is funneled to /change-password until it sets a real one.
function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <Spinner text="Loading..." />;
  if (!user) return <Navigate to="/login" replace />;
  if (user.must_change_password) return <Navigate to="/change-password" replace />;
  return children;
}

function AppRoutes() {
  const { user, loading } = useAuth();

  const page = (el) => (
    <ProtectedRoute>
      <Layout>{el}</Layout>
    </ProtectedRoute>
  );

  return (
    <Routes>
      <Route
        path="/login"
        element={loading ? <Spinner text="Loading..." /> : user ? <Navigate to="/home" replace /> : <Login />}
      />
      <Route
        path="/register"
        element={loading ? <Spinner text="Loading..." /> : user ? <Navigate to="/home" replace /> : <Register />}
      />
      {/* Reachable while authenticated (forced or voluntary password change). */}
      <Route
        path="/change-password"
        element={loading ? <Spinner text="Loading..." /> : user ? <ChangePassword /> : <Navigate to="/login" replace />}
      />
      <Route path="/" element={<Navigate to="/home" replace />} />
      <Route path="/home" element={page(<Home />)} />
      <Route path="/log" element={page(<LogMeal />)} />
      <Route path="/timeline" element={page(<Timeline />)} />
      <Route path="/monthly" element={page(<Monthly />)} />
      <Route path="/settings" element={page(<Settings />)} />
      <Route path="*" element={<Navigate to="/home" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <LogDraftProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </LogDraftProvider>
    </AuthProvider>
  );
}
