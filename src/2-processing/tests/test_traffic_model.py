import pandas as pd
import pytest

from log_parser.parser import parse_logs
from traffic_model.markov import END, build_markov_matrix, build_markov_model
from traffic_model.scaling import predict_traffic_scale
from traffic_model.think_time import build_think_times


def test_markov_transitions_follow_each_session(log_file):
    matrix = build_markov_matrix(parse_logs(log_file))
    # a: users -> accounts -> transfers ; b: users -> transfers
    assert matrix["GET /api/users/{id}"] == {"GET /api/accounts/{id}": 0.5, "POST /api/transfers": 0.5}
    assert matrix["GET /api/accounts/{id}"] == {"POST /api/transfers": 1.0}
    assert "POST /api/transfers" not in matrix


def test_markov_rows_sum_to_one(log_file):
    for targets in build_markov_matrix(parse_logs(log_file)).values():
        assert sum(targets.values()) == pytest.approx(1.0)


def test_markov_requires_session_field():
    df = pd.DataFrame({"timestamp": [1, 2], "method": ["GET"] * 2, "endpoint": ["/a", "/b"], "session_id": [None, None]})
    with pytest.raises(ValueError, match="sesion"):
        build_markov_matrix(df)


def test_model_has_start_and_end(log_file):
    model = build_markov_model(parse_logs(log_file))
    # Las dos sesiones empiezan por users y terminan en transfers
    assert model["start"] == {"GET /api/users/{id}": 1.0}
    assert model["transitions"]["POST /api/transfers"] == {END: 1.0}
    assert model["states"] == ["GET /api/accounts/{id}", "GET /api/users/{id}", "POST /api/transfers"]
    for distribution in [model["start"], *model["transitions"].values()]:
        assert sum(distribution.values()) == pytest.approx(1.0)


def test_model_prunes_and_renormalizes():
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-10-01", periods=10, freq="s"),
        "method": ["GET"] * 10,
        "endpoint": ["/a", "/b"] * 4 + ["/a", "/c"],
        "session_id": ["s"] * 10,
    })
    # /a -> /b 4 veces, /a -> /c 1 vez
    transitions = build_markov_model(df, min_probability=0.3)["transitions"]
    assert transitions["GET /a"] == {"GET /b": 1.0}


def test_think_times_per_transition(log_file):
    think = build_think_times(parse_logs(log_file), samples=5)
    # sesión a: users (09:00:01) -> accounts (09:00:03) ; b: users (09:00:02) -> transfers (09:00:04)
    assert think["GET /api/users/{id}"]["GET /api/accounts/{id}"] == [2000] * 5
    assert think["GET /api/accounts/{id}"]["POST /api/transfers"] == [2000] * 5
    assert "POST /api/transfers" not in think


def test_think_times_are_capped():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-10-01T09:00:00", "2026-10-01T10:00:00"]),
        "method": ["GET", "GET"], "endpoint": ["/a", "/b"], "session_id": ["s", "s"],
    })
    assert build_think_times(df, samples=3, max_ms=5000)["GET /a"]["GET /b"] == [5000] * 3


def test_scaling(log_file):
    profile = predict_traffic_scale(parse_logs(log_file))
    assert profile == {"vusers": 3, "ramp_up_seconds": 60, "duration_seconds": 300}
