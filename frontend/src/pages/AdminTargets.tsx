import TargetTable from "../components/admin/TargetTable";
import RequireAuth from "../components/admin/RequireAuth";

export default function AdminTargets() {
  return (
    <RequireAuth>
      <h2>Targets</h2>
      <TargetTable />
    </RequireAuth>
  );
}
