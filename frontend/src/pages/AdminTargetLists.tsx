import TargetListTable from "../components/admin/TargetListTable";
import RequireAuth from "../components/admin/RequireAuth";

export default function AdminTargetLists() {
  return (
    <RequireAuth>
      <h2>Target lists</h2>
      <p className="admin-hint">
        A target list is a URL to a plaintext file with one hostname or IP per line (blank lines and
        lines starting with # are ignored). It's re-fetched on its interval, and targets are added or
        removed to match.
      </p>
      <TargetListTable />
    </RequireAuth>
  );
}
