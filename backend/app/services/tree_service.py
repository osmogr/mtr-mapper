import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.schemas.tree import NodeStatsUpdate, TreeDiffMessage, TreeNode, TreeSnapshotMessage
from app.services import asn_lookup, hostname_lookup, tree_builder
from app.services.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)


class TreeService:
    def __init__(self) -> None:
        self._nodes: dict[str, TreeNode] = {}
        self._seq = 0
        self._lock = asyncio.Lock()
        self._recompute_needed = asyncio.Event()

    def request_recompute(self) -> None:
        self._recompute_needed.set()

    async def snapshot_message(self) -> TreeSnapshotMessage:
        async with self._lock:
            return TreeSnapshotMessage(seq=self._seq, nodes=list(self._nodes.values()))

    async def _recompute(self, session_maker: async_sessionmaker, settings: Settings) -> TreeDiffMessage | None:
        async with session_maker() as session:
            traces = await tree_builder.load_target_traces(session)
            hop_ips = {h.hop_ip for t in traces for h in t.hops if h.hop_ip}
            asn_map = await asn_lookup.get_asn_map(session, hop_ips, settings)
            hostname_map = await hostname_lookup.get_hostname_map(session, hop_ips, settings)
        current_nodes = tree_builder.build_tree(traces, settings, asn_map, hostname_map)
        now = datetime.now(timezone.utc)
        fade_window = timedelta(hours=settings.path_fade_hours)

        async with self._lock:
            old_nodes = self._nodes

            # Current nodes are always fresh. Anything that just dropped out of
            # the current build is kept around as a fading "ghost" -- still an
            # ordinary TreeNode, just marked not-current -- until it's aged
            # past the fade window, at which point it's dropped for real. This
            # is what lets a rerouted path stay visible and dim out instead of
            # vanishing the instant it's no longer part of any active trace.
            merged: dict[str, TreeNode] = {
                nid: n.model_copy(update={"is_current": True, "last_seen_at": now})
                for nid, n in current_nodes.items()
            }
            for nid, old in old_nodes.items():
                if nid in merged:
                    continue
                if old.last_seen_at is not None and now - old.last_seen_at < fade_window:
                    merged[nid] = old.model_copy(update={"is_current": False})

            added: list[TreeNode] = []
            updated: list[NodeStatsUpdate] = []
            for nid, n in merged.items():
                old = old_nodes.get(nid)
                if old is None:
                    added.append(n)
                    continue
                if (
                    old.own_stats != n.own_stats
                    or old.severity != n.severity
                    or old.worst_descendant_severity != n.worst_descendant_severity
                    or old.hop_hostname != n.hop_hostname
                    or old.hop_ips != n.hop_ips
                    or old.asn != n.asn
                    or old.as_org != n.as_org
                    or old.is_current != n.is_current
                ):
                    updated.append(
                        NodeStatsUpdate(
                            id=nid,
                            own_stats=n.own_stats,
                            severity=n.severity,
                            worst_descendant_severity=n.worst_descendant_severity,
                            hop_hostname=n.hop_hostname,
                            hop_ips=n.hop_ips,
                            asn=n.asn,
                            as_org=n.as_org,
                            is_current=n.is_current,
                            last_seen_at=n.last_seen_at,
                        )
                    )

            removed = [nid for nid in old_nodes if nid not in merged]

            if not added and not removed and not updated:
                self._nodes = merged
                return None

            self._seq += 1
            self._nodes = merged
            return TreeDiffMessage(seq=self._seq, added=added, updated=updated, removed=removed)

    async def recompute_and_broadcast(
        self, session_maker: async_sessionmaker, settings: Settings, ws_manager: ConnectionManager
    ) -> None:
        try:
            diff = await self._recompute(session_maker, settings)
        except Exception:
            logger.exception("tree recompute failed")
            return
        if diff is not None:
            await ws_manager.broadcast(diff.model_dump(mode="json"))

    async def debounce_loop(
        self,
        session_maker: async_sessionmaker,
        settings: Settings,
        ws_manager: ConnectionManager,
        interval_seconds: float,
    ) -> None:
        # Prime the tree once at startup so early connections get real data.
        await self.recompute_and_broadcast(session_maker, settings, ws_manager)
        while True:
            await self._recompute_needed.wait()
            self._recompute_needed.clear()
            await asyncio.sleep(interval_seconds)
            self._recompute_needed.clear()
            await self.recompute_and_broadcast(session_maker, settings, ws_manager)

    async def get_node(self, node_id: str) -> TreeNode | None:
        async with self._lock:
            return self._nodes.get(node_id)


tree_service = TreeService()
