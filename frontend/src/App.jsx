import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ProfileProvider, useProfile } from "./context/ProfileContext";
import { LogDraftProvider } from "./context/LogDraftContext";
import ProfileSelect from "./pages/ProfileSelect";
import Home from "./pages/Home";
import LogMeal from "./pages/LogMeal";
import Timeline from "./pages/Timeline";
import Monthly from "./pages/Monthly";
import Settings from "./pages/Settings";
import Layout from "./components/layout/Layout";

function ProtectedRoute({ children }) {
  const { profile } = useProfile();
  if (!profile) return <Navigate to="/" replace />;
  return children;
}

function AppRoutes() {
  const { profile } = useProfile();
  return (
    <Routes>
      <Route path="/" element={profile ? <Navigate to="/home" replace /> : <ProfileSelect />} />
      <Route path="/home" element={<ProtectedRoute><Layout><Home /></Layout></ProtectedRoute>} />
      <Route path="/log" element={<ProtectedRoute><Layout><LogMeal /></Layout></ProtectedRoute>} />
      <Route path="/timeline" element={<ProtectedRoute><Layout><Timeline /></Layout></ProtectedRoute>} />
      <Route path="/monthly" element={<ProtectedRoute><Layout><Monthly /></Layout></ProtectedRoute>} />
      <Route path="/settings" element={<ProtectedRoute><Layout><Settings /></Layout></ProtectedRoute>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <ProfileProvider>
      <LogDraftProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </LogDraftProvider>
    </ProfileProvider>
  );
}
