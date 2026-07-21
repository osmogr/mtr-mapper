import { Navigate, Route, Routes } from "react-router-dom";

import AdminLogin from "./pages/AdminLogin";
import AdminTargetLists from "./pages/AdminTargetLists";
import AdminTargets from "./pages/AdminTargets";
import TreeView from "./pages/TreeView";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<TreeView />} />
      <Route path="/admin" element={<Navigate to="/admin/targets" replace />} />
      <Route path="/admin/login" element={<AdminLogin />} />
      <Route path="/admin/targets" element={<AdminTargets />} />
      <Route path="/admin/target-lists" element={<AdminTargetLists />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
