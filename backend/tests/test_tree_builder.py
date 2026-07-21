from app.config import Settings
from app.services.tree_builder import HopRecord, TargetTraceData, build_tree

SETTINGS = Settings(loss_warn_threshold=2.0, loss_critical_threshold=20.0)


def hop(number, ip=None, timeout=False, loss=0.0, avg=10.0, sent=5):
    return HopRecord(
        hop_number=number,
        hop_ip=ip,
        hop_hostname=None,
        is_timeout=timeout,
        sent=sent,
        loss_pct=loss,
        last_ms=avg,
        avg_ms=avg,
        best_ms=avg,
        worst_ms=avg,
        stddev_ms=0.0,
    )


def test_shared_trunk_collapses_and_diverges():
    traces = [
        TargetTraceData(
            target_id=1,
            address="a.example.com",
            hops=[hop(1, "10.0.0.1"), hop(2, "10.0.0.2"), hop(3, "1.1.1.1")],
        ),
        TargetTraceData(
            target_id=2,
            address="b.example.com",
            hops=[hop(1, "10.0.0.1"), hop(2, "10.0.0.2"), hop(3, "8.8.8.8")],
        ),
    ]
    nodes = build_tree(traces, SETTINGS)

    hop1_nodes = [n for n in nodes.values() if n.hop_ip == "10.0.0.1"]
    hop2_nodes = [n for n in nodes.values() if n.hop_ip == "10.0.0.2"]
    assert len(hop1_nodes) == 1, "shared first hop must collapse into a single node"
    assert len(hop2_nodes) == 1, "shared second hop must collapse into a single node"

    hop3_nodes = [
        n for n in nodes.values() if n.hop_ip in ("1.1.1.1", "8.8.8.8") and not n.is_leaf_target
    ]
    assert len(hop3_nodes) == 2, "divergent third hop must produce two distinct real-hop nodes"
    assert hop3_nodes[0].parent_id == hop2_nodes[0].id
    assert hop3_nodes[1].parent_id == hop2_nodes[0].id

    leaves = [n for n in nodes.values() if n.is_leaf_target]
    assert len(leaves) == 2
    assert {leaf.target_ids[0] for leaf in leaves} == {1, 2}


def test_simultaneous_timeout_on_shared_trunk_merges():
    traces = [
        TargetTraceData(
            target_id=1,
            address="a.example.com",
            hops=[hop(1, "10.0.0.1"), hop(2, timeout=True)],
        ),
        TargetTraceData(
            target_id=2,
            address="b.example.com",
            hops=[hop(1, "10.0.0.1"), hop(2, timeout=True)],
        ),
    ]
    nodes = build_tree(traces, SETTINGS)
    timeout_nodes = [n for n in nodes.values() if n.is_timeout_node]
    assert len(timeout_nodes) == 1, "identical shared-trunk timeouts should merge into one node"


def test_timeout_after_divergence_does_not_merge():
    traces = [
        TargetTraceData(
            target_id=1,
            address="a.example.com",
            hops=[hop(1, "10.0.0.1"), hop(2, timeout=True)],
        ),
        TargetTraceData(
            target_id=2,
            address="b.example.com",
            hops=[hop(1, "10.0.0.2"), hop(2, timeout=True)],
        ),
    ]
    nodes = build_tree(traces, SETTINGS)
    timeout_nodes = [n for n in nodes.values() if n.is_timeout_node]
    assert len(timeout_nodes) == 2, "timeouts under different parents must not be merged"
    assert timeout_nodes[0].parent_id != timeout_nodes[1].parent_id


def test_same_ip_at_different_depth_not_merged():
    traces = [
        TargetTraceData(
            target_id=1,
            address="a.example.com",
            hops=[hop(1, "192.0.2.1")],
        ),
        TargetTraceData(
            target_id=2,
            address="b.example.com",
            hops=[hop(1, "192.0.2.9"), hop(2, "192.0.2.1")],
        ),
    ]
    nodes = build_tree(traces, SETTINGS)
    ip_nodes = [n for n in nodes.values() if n.hop_ip == "192.0.2.1" and not n.is_leaf_target]
    assert len(ip_nodes) == 2, "same IP at different depths/parents must remain distinct nodes"
    assert {n.depth for n in ip_nodes} == {1, 2}


def test_severity_thresholds_and_worst_descendant_bubbles_up():
    traces = [
        TargetTraceData(
            target_id=1,
            address="a.example.com",
            hops=[hop(1, "10.0.0.1", loss=0.0), hop(2, "1.1.1.1", loss=50.0)],
        ),
    ]
    nodes = build_tree(traces, SETTINGS)
    hop1 = next(n for n in nodes.values() if n.hop_ip == "10.0.0.1")
    hop2 = next(n for n in nodes.values() if n.hop_ip == "1.1.1.1")
    assert hop1.severity == "ok"
    assert hop2.severity == "critical"
    # The healthy shared hop should still flag the downstream problem.
    assert hop1.worst_descendant_severity == "critical"


def test_target_with_no_data_yet_is_unknown_leaf_under_root():
    from app.services.tree_builder import ROOT_ID

    traces = [TargetTraceData(target_id=1, address="pending.example.com", hops=[])]
    nodes = build_tree(traces, SETTINGS)
    leaves = [n for n in nodes.values() if n.is_leaf_target]
    assert len(leaves) == 1
    assert leaves[0].parent_id == ROOT_ID
    assert leaves[0].severity == "unknown"
