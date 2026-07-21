import math

import pytest

from app.scamper_runner import _parse_scamper_trace, _resolve_address

# Shapes below match real `scamper -O json -I 'trace -P icmp-paris ...'`
# output (captured against a live scamper 20211212 binary), trimmed to the
# fields _parse_scamper_trace actually reads.


def _probe(ttl, probe_id, addr, rtt):
    return {"addr": addr, "probe_ttl": ttl, "probe_id": probe_id, "rtt": rtt}


def test_parses_hops_and_flags_timeout():
    # ttl 2 got zero replies across all attempts -- scamper omits it
    # entirely rather than emitting a placeholder like mtr's "???".
    trace = {
        "hop_count": 3,
        "attempts": 1,
        "hops": [
            _probe(1, 1, "10.0.0.1", 1.2),
            _probe(3, 1, "1.1.1.1", 12.4),
        ],
    }
    hops = _parse_scamper_trace(trace)
    assert len(hops) == 3

    assert hops[0].hop_number == 1
    assert hops[0].hop_ip == "10.0.0.1"
    assert hops[0].is_timeout is False

    assert hops[1].hop_number == 2
    assert hops[1].hop_ip is None
    assert hops[1].is_timeout is True
    assert hops[1].loss_pct == 100.0

    assert hops[2].hop_ip == "1.1.1.1"
    assert hops[2].last_ms == 12.4


def test_empty_hops_returns_empty_list():
    assert _parse_scamper_trace({"hop_count": 0, "attempts": 1, "hops": []}) == []


def test_aggregates_multi_attempt_stats():
    trace = {
        "hop_count": 1,
        "attempts": 3,
        "hops": [
            _probe(1, 1, "10.0.0.1", 1.0),
            _probe(1, 2, "10.0.0.1", 1.5),
            _probe(1, 3, "10.0.0.1", 2.0),
        ],
    }
    hops = _parse_scamper_trace(trace)
    assert len(hops) == 1
    hop = hops[0]
    assert hop.sent == 3
    assert hop.loss_pct == 0.0
    assert hop.last_ms == 2.0
    assert hop.best_ms == 1.0
    assert hop.worst_ms == 2.0
    assert math.isclose(hop.avg_ms, 1.5)
    assert math.isclose(hop.stddev_ms, math.sqrt(((1 - 1.5) ** 2 + 0 + (2 - 1.5) ** 2) / 3))


def test_partial_loss_within_a_hop():
    trace = {
        "hop_count": 1,
        "attempts": 3,
        "hops": [
            _probe(1, 1, "10.0.0.1", 1.0),
            _probe(1, 3, "10.0.0.1", 3.0),
        ],
    }
    hops = _parse_scamper_trace(trace)
    assert hops[0].sent == 3
    assert math.isclose(hops[0].loss_pct, 100.0 * (1 / 3))


def test_divergent_addr_within_hop_group_resolves_deterministically():
    # A real mid-run route change (not ECMP noise, since Paris-consistency
    # should pin the flow) -- must resolve to one IP, not crash or drop it.
    trace = {
        "hop_count": 1,
        "attempts": 2,
        "hops": [
            _probe(1, 1, "1.2.3.4", 1.0),
            _probe(1, 2, "5.6.7.8", 1.1),
        ],
    }
    hops = _parse_scamper_trace(trace)
    assert len(hops) == 1
    assert hops[0].hop_ip == "5.6.7.8"


def test_filters_gateway_hop_and_renumbers():
    trace = {
        "hop_count": 3,
        "attempts": 1,
        "hops": [
            _probe(1, 1, "172.26.0.1", 0.5),
            _probe(2, 1, "10.0.0.1", 1.2),
            _probe(3, 1, "1.1.1.1", 12.4),
        ],
    }
    hops = _parse_scamper_trace(trace, gateway_ip="172.26.0.1")
    assert len(hops) == 2, "the container's own gateway hop must be dropped"
    assert hops[0].hop_ip == "10.0.0.1"
    assert hops[0].hop_number == 1, "hops are renumbered sequentially after filtering, no gap left"
    assert hops[1].hop_ip == "1.1.1.1"
    assert hops[1].hop_number == 2


def test_no_gateway_ip_keeps_all_hops():
    trace = {
        "hop_count": 1,
        "attempts": 1,
        "hops": [_probe(1, 1, "10.0.0.1", 1.0)],
    }
    hops = _parse_scamper_trace(trace, gateway_ip=None)
    assert len(hops) == 1


@pytest.mark.asyncio
async def test_resolve_address_passes_through_ipv4_literal():
    # scamper's -I driver has no resolver of its own -- a bare hostname
    # target makes the whole `trace` sub-command silently fail with no
    # output, so run_scamper() must resolve first. IP literals must pass
    # through untouched rather than round-tripping through DNS.
    assert await _resolve_address("8.8.8.8") == "8.8.8.8"


@pytest.mark.asyncio
async def test_resolve_address_passes_through_ipv6_literal():
    assert await _resolve_address("::1") == "::1"
