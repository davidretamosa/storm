"""La millora del trànsit habitual (T-1, --ai-traffic). Logs sintètics fets aquí mateix: cap dada real."""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from ai.enhancements import traffic_stats
from ai.tests.support import ROOT
from log_parser.parser import parse_logs
from traffic_model.payloads import build_path_params
from traffic_model.think_time import build_think_times

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def in_processing(monkeypatch):
    monkeypatch.chdir(ROOT)


def line(second, session, endpoint="/api/accounts/{id}", path="/api/accounts/1", method="GET", status=200,
         duration=None, user=1):
    entry = {"timestamp": (T0 + timedelta(seconds=second)).isoformat().replace("+00:00", "Z"),
             "sessionId": session, "userId": user, "method": method, "endpoint": endpoint, "path": path,
             "status": status}
    if duration is not None:
        entry["durationMs"] = duration
    return entry


def write_log(tmp_path, entries, name="log.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def read(tmp_path, entries):
    return parse_logs(str(write_log(tmp_path, entries)))


# --- traffic_stats: pauses netes ------------------------------------------------------------------

def test_net_pauses_subtract_the_previous_response_time(tmp_path):
    df = read(tmp_path, [line(0, "s1", duration=500), line(3, "s1", duration=200), line(4, "s1", duration=9)])
    net = traffic_stats.net_pauses(df)
    pauses = net.groupby("session_id")["timestamp"].diff().dt.total_seconds().dropna().tolist()
    assert pauses == [2.5, 0.8]                                  # 3 - 0,5 i 1 - 0,2
    assert net["timestamp"].iloc[0] == df["timestamp"].iloc[0]   # la sessió comença on començava


def test_net_pauses_never_go_negative(tmp_path):
    """Una petició que respon més lent del que tarda la següent a arribar: la pausa és 0, no negativa."""
    df = read(tmp_path, [line(0, "s1", duration=5000), line(1, "s1"), line(2, "s1")])
    net = traffic_stats.net_pauses(df)
    pauses = net["timestamp"].diff().dt.total_seconds().dropna().tolist()
    assert pauses == [0.0, 1.0]


def test_net_pauses_reach_the_think_times_of_the_team(tmp_path):
    df = read(tmp_path, [line(0, "s1", duration=1000), line(5, "s1", "/api/users/{id}", "/api/users/1")])
    original = build_think_times(df)["GET /api/accounts/{id}"]["GET /api/users/{id}"]
    net = build_think_times(traffic_stats.net_pauses(df))["GET /api/accounts/{id}"]["GET /api/users/{id}"]
    assert set(original) == {5000} and set(net) == {4000}


def test_net_pauses_keep_sessions_apart_and_leave_the_input_alone(tmp_path):
    df = read(tmp_path, [line(0, "a", duration=100), line(1, "b", duration=900), line(2, "a"), line(3, "b")])
    before = df.copy()
    net = traffic_stats.net_pauses(df)
    gaps = {s: g["timestamp"].diff().dt.total_seconds().dropna().tolist() for s, g in net.groupby("session_id")}
    assert gaps == {"a": [1.9], "b": [1.1]}
    pd.testing.assert_frame_equal(df, before)


def test_without_durations_the_log_is_untouched(tmp_path):
    df = read(tmp_path, [line(0, "s1"), line(3, "s1")])
    assert traffic_stats.net_pauses(df) is df


# --- traffic_stats: errors ------------------------------------------------------------------------

def test_path_ids_are_learned_only_from_successful_requests(tmp_path):
    df = read(tmp_path, [line(0, "s1", path="/api/accounts/1"), line(1, "s1", path="/api/accounts/2"),
                         line(2, "s1", path="/api/accounts/999", status=404)])
    with_404 = build_path_params(df)["GET /api/accounts/{id}"]["id"]
    clean = build_path_params(traffic_stats.successful(df))["GET /api/accounts/{id}"]["id"]
    assert "999" in [v for v, _ in with_404]                  # sense la millora, el 404 s'hi cola
    assert sorted(v for v, _ in clean) == ["1", "2"]


def test_a_request_with_no_success_keeps_its_ids(tmp_path):
    """Si una petició no ha anat bé mai, no es filtra: si no, sortiria del pla i JMeter posaria un 1."""
    df = read(tmp_path, [line(0, "s1", "/api/users/{id}", "/api/users/7", status=404),
                         line(1, "s1", path="/api/accounts/1")])
    params = build_path_params(traffic_stats.successful(df))
    assert params["GET /api/users/{id}"]["id"] == [["7", 1.0]]


def test_without_status_nothing_is_filtered(tmp_path):
    entries = [line(0, "s1"), line(1, "s1", path="/api/accounts/2")]
    for entry in entries:
        del entry["status"]
    df = read(tmp_path, entries)
    assert traffic_stats.successful(df) is df
    assert traffic_stats.error_rates(df) == {}


def test_error_rates(tmp_path):
    df = read(tmp_path, [line(0, "s1"), line(1, "s1", status=404), line(2, "s1", status=503),
                         line(3, "s1", status=201), line(4, "s1", "/api/users", "/api/users", "POST")])
    assert traffic_stats.error_rates(df) == {
        "GET /api/accounts/{id}": {"requests": 4, "4xx": 0.25, "5xx": 0.25},
        "POST /api/users": {"requests": 1, "4xx": 0.0, "5xx": 0.0},
    }


def test_reference_durations(tmp_path):
    df = read(tmp_path, [line(i, "s1", duration=d) for i, d in enumerate(range(1, 21))])   # 1..20 ms
    durations = traffic_stats.reference_durations(df)["GET /api/accounts/{id}"]
    assert durations == {"requests": 20, "p50_ms": 10.5, "p95_ms": 19.05}
