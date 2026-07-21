from app.mtr_runner import _parse_mtr_json

SAMPLE_MTR_JSON = {
    "report": {
        "mtr": {"src": "prober", "dst": "1.1.1.1", "tos": 0},
        "hubs": [
            {
                "count": 1,
                "host": "10.0.0.1",
                "Loss%": 0.0,
                "Snt": 5,
                "Last": 1.2,
                "Avg": 1.5,
                "Best": 1.1,
                "Wrst": 2.0,
                "StDev": 0.3,
            },
            {
                "count": 2,
                "host": "???",
                "Loss%": 100.0,
                "Snt": 5,
                "Last": 0.0,
                "Avg": 0.0,
                "Best": 0.0,
                "Wrst": 0.0,
                "StDev": 0.0,
            },
            {
                "count": 3,
                "host": "1.1.1.1",
                "Loss%": 0.0,
                "Snt": 5,
                "Last": 12.4,
                "Avg": 12.1,
                "Best": 11.9,
                "Wrst": 12.9,
                "StDev": 0.4,
            },
        ],
    }
}


def test_parses_hops_and_flags_timeout():
    hops = _parse_mtr_json(SAMPLE_MTR_JSON)
    assert len(hops) == 3

    assert hops[0].hop_number == 1
    assert hops[0].hop_ip == "10.0.0.1"
    assert hops[0].is_timeout is False

    assert hops[1].hop_number == 2
    assert hops[1].hop_ip is None
    assert hops[1].is_timeout is True

    assert hops[2].hop_ip == "1.1.1.1"
    assert hops[2].avg_ms == 12.1


def test_empty_hubs_returns_empty_list():
    assert _parse_mtr_json({"report": {"hubs": []}}) == []
