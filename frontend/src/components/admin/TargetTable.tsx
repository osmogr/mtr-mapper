import { useEffect, useState, type FormEvent } from "react";

import { api } from "../../api/client";
import type { Target } from "../../api/types";

export default function TargetTable() {
  const [targets, setTargets] = useState<Target[]>([]);
  const [q, setQ] = useState("");
  const [address, setAddress] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function reload() {
    setLoading(true);
    try {
      setTargets(await api.adminListTargets(q ? { q } : undefined));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.adminCreateTarget(address.trim(), displayName.trim() || undefined);
      setAddress("");
      setDisplayName("");
      await reload();
    } catch {
      setError("Could not add target — check the address and try again.");
    }
  }

  async function handleToggleActive(t: Target) {
    await api.adminUpdateTarget(t.id, { active: !t.active });
    await reload();
  }

  async function handleDelete(t: Target) {
    if (!confirm(`Remove ${t.address}?`)) return;
    await api.adminDeleteTarget(t.id);
    await reload();
  }

  return (
    <div>
      <form className="admin-add-form" onSubmit={handleAdd}>
        <input
          placeholder="Hostname or IP (e.g. 1.1.1.1 or example.com)"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          required
        />
        <input
          placeholder="Display name (optional)"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
        <button type="submit">Add target</button>
      </form>
      {error && <p className="error-text">{error}</p>}

      <input
        className="admin-search"
        placeholder="Filter…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />

      {loading ? (
        <p>Loading…</p>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Address</th>
              <th>Name</th>
              <th>Sources</th>
              <th>Active</th>
              <th>Last probed</th>
              <th>Last result</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {targets.map((t) => (
              <tr key={t.id}>
                <td>{t.address}</td>
                <td>{t.display_name ?? ""}</td>
                <td>{t.sources.join(", ")}</td>
                <td>{t.active ? "yes" : "no"}</td>
                <td>{t.last_probed_at ? new Date(t.last_probed_at).toLocaleString() : "never"}</td>
                <td>{t.last_probe_success === null ? "-" : t.last_probe_success ? "ok" : "failed"}</td>
                <td>
                  <button onClick={() => handleToggleActive(t)}>
                    {t.active ? "Deactivate" : "Activate"}
                  </button>
                  <button onClick={() => handleDelete(t)} className="danger">
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {targets.length === 0 && (
              <tr>
                <td colSpan={7}>No targets yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
