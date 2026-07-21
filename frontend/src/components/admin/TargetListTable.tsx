import { useEffect, useState, type FormEvent } from "react";

import { api } from "../../api/client";
import type { TargetList } from "../../api/types";

export default function TargetListTable() {
  const [lists, setLists] = useState<TargetList[]>([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [intervalSeconds, setIntervalSeconds] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncingId, setSyncingId] = useState<number | null>(null);

  async function reload() {
    setLoading(true);
    try {
      setLists(await api.adminListTargetLists());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reload();
  }, []);

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.adminCreateTargetList({
        name: name.trim(),
        url: url.trim(),
        fetch_interval_seconds: intervalSeconds === "" ? undefined : Number(intervalSeconds),
      });
      setName("");
      setUrl("");
      setIntervalSeconds("");
      await reload();
    } catch {
      setError("Could not add list — check the URL and try again.");
    }
  }

  async function handleSyncNow(id: number) {
    setSyncingId(id);
    try {
      await api.adminSyncTargetListNow(id);
      await reload();
    } finally {
      setSyncingId(null);
    }
  }

  async function handleToggleActive(l: TargetList) {
    await api.adminUpdateTargetList(l.id, { active: !l.active });
    await reload();
  }

  async function handleDelete(l: TargetList) {
    if (!confirm(`Remove list "${l.name}"? Targets only sourced from it will be deactivated.`)) return;
    await api.adminDeleteTargetList(l.id);
    await reload();
  }

  return (
    <div>
      <form className="admin-add-form" onSubmit={handleAdd}>
        <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
        <input
          placeholder="https://example.com/targets.txt"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
        />
        <input
          type="number"
          placeholder="Fetch interval (s)"
          value={intervalSeconds}
          onChange={(e) => setIntervalSeconds(e.target.value === "" ? "" : Number(e.target.value))}
        />
        <button type="submit">Add list</button>
      </form>
      {error && <p className="error-text">{error}</p>}

      {loading ? (
        <p>Loading…</p>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>URL</th>
              <th>Interval</th>
              <th>Active</th>
              <th>Last sync</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {lists.map((l) => (
              <tr key={l.id}>
                <td>{l.name}</td>
                <td className="truncate">{l.url}</td>
                <td>{l.fetch_interval_seconds}s</td>
                <td>{l.active ? "yes" : "no"}</td>
                <td>{l.last_fetched_at ? new Date(l.last_fetched_at).toLocaleString() : "never"}</td>
                <td>
                  {l.last_fetch_status === "error" ? (
                    <span className="error-text" title={l.last_fetch_error ?? ""}>
                      error
                    </span>
                  ) : l.last_fetch_status === "ok" ? (
                    `ok (${l.last_fetch_target_count ?? 0})`
                  ) : (
                    "-"
                  )}
                </td>
                <td>
                  <button onClick={() => handleSyncNow(l.id)} disabled={syncingId === l.id}>
                    {syncingId === l.id ? "Syncing…" : "Sync now"}
                  </button>
                  <button onClick={() => handleToggleActive(l)}>{l.active ? "Deactivate" : "Activate"}</button>
                  <button onClick={() => handleDelete(l)} className="danger">
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {lists.length === 0 && (
              <tr>
                <td colSpan={7}>No target lists yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
