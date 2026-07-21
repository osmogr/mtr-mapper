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

    hop3_nodes = [n for n in nodes.values() if n.hop_ip in ("1.1.1.1", "8.8.8.8")]
    assert len(hop3_nodes) == 2, "divergent third hop must produce two distinct nodes"
    assert all(n.is_leaf_target for n in hop3_nodes), (
        "a responding final hop folds directly into the leaf-target node, no separate sibling"
    )
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
    ip_nodes = [n for n in nodes.values() if n.hop_ip == "192.0.2.1"]
    assert len(ip_nodes) == 2, "same IP at different depths/parents must remain distinct nodes"
    assert {n.depth for n in ip_nodes} == {1, 2}


def test_same_hostname_different_ip_merges():
    traces = [
        TargetTraceData(
            target_id=1,
            address="a.example.com",
            hops=[hop(1, "10.0.0.1"), hop(2, "1.1.1.1")],
        ),
        TargetTraceData(
            target_id=2,
            address="b.example.com",
            hops=[hop(1, "10.0.0.2"), hop(2, "8.8.8.8")],
        ),
    ]
    hostname_map = {"10.0.0.1": "router.example.net", "10.0.0.2": "router.example.net"}
    nodes = build_tree(traces, SETTINGS, hostname_map=hostname_map)

    trunk_nodes = [n for n in nodes.values() if n.depth == 1]
    assert len(trunk_nodes) == 1, "two IPs sharing a hostname at the same trie position must merge"
    merged = trunk_nodes[0]
    assert not merged.is_leaf_target
    assert merged.hop_hostname == "router.example.net"
    assert set(merged.hop_ips) == {"10.0.0.1", "10.0.0.2"}
    assert merged.hop_ip == "10.0.0.1", "primary hop_ip stays the first-seen IP"

    leaves = [n for n in nodes.values() if n.is_leaf_target]
    assert len(leaves) == 2
    assert {leaf.target_ids[0] for leaf in leaves} == {1, 2}


def test_no_hostname_different_ip_stays_separate():
    traces = [
        TargetTraceData(
            target_id=1,
            address="a.example.com",
            hops=[hop(1, "10.0.0.1"), hop(2, "1.1.1.1")],
        ),
        TargetTraceData(
            target_id=2,
            address="b.example.com",
            hops=[hop(1, "10.0.0.2"), hop(2, "8.8.8.8")],
        ),
    ]
    nodes = build_tree(traces, SETTINGS, hostname_map={})

    trunk_nodes = [n for n in nodes.values() if n.depth == 1]
    assert len(trunk_nodes) == 2, "without a shared hostname, different IPs must stay distinct"


def test_identical_full_path_via_hostname_alias_shares_one_leaf():
    traces = [
        TargetTraceData(target_id=1, address="a.example.com", hops=[hop(1, "10.0.0.1")]),
        TargetTraceData(target_id=2, address="b.example.com", hops=[hop(1, "10.0.0.2")]),
    ]
    hostname_map = {"10.0.0.1": "router.example.net", "10.0.0.2": "router.example.net"}
    nodes = build_tree(traces, SETTINGS, hostname_map=hostname_map)

    leaves = [n for n in nodes.values() if n.is_leaf_target]
    assert len(leaves) == 1, "identical full paths (via hostname alias) reach the same destination node"
    assert set(leaves[0].target_ids) == {1, 2}
    assert set(leaves[0].hop_ips) == {"10.0.0.1", "10.0.0.2"}


def test_responding_destination_folds_into_single_leaf_node():
    traces = [
        TargetTraceData(
            target_id=1,
            address="dns.google",
            hops=[hop(1, "10.0.0.1"), hop(2, "8.8.8.8")],
        ),
    ]
    nodes = build_tree(traces, SETTINGS)
    matching = [n for n in nodes.values() if n.hop_ip == "8.8.8.8"]
    assert len(matching) == 1, "a responding final hop must not also get a separate redundant leaf sibling"
    leaf = matching[0]
    assert leaf.is_leaf_target
    assert leaf.target_ids == [1]
    assert leaf.children == []


def test_unresponsive_destination_keeps_separate_leaf_marker():
    traces = [
        TargetTraceData(
            target_id=1,
            address="dark.example.com",
            hops=[hop(1, "10.0.0.1"), hop(2, timeout=True)],
        ),
    ]
    nodes = build_tree(traces, SETTINGS)
    timeout_node = next(n for n in nodes.values() if n.is_timeout_node)
    assert not timeout_node.is_leaf_target
    leaves = [n for n in nodes.values() if n.is_leaf_target]
    assert len(leaves) == 1
    assert leaves[0].parent_id == timeout_node.id
    assert leaves[0].target_ids == [1]


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
