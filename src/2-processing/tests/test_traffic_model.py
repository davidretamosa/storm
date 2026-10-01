import pandas as pd
import pytest

from log_parser.parser import parse_logs
from traffic_model.markov import build_markov_matrix
from traffic_model.scaling import predict_traffic_scale


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


def test_scaling(log_file):
    profile = predict_traffic_scale(parse_logs(log_file))
    assert profile == {"vusers": 3, "ramp_up_seconds": 60, "duration_seconds": 300}
