import pandas as pd
import pytest

from log_parser.parser import parse_logs
from traffic_model.payloads import build_body_models, build_path_params


def requests(*rows):
    return pd.DataFrame(rows, columns=["method", "endpoint", "path", "body"])


def test_path_params_from_observed_paths(log_file):
    params = build_path_params(parse_logs(log_file))
    assert params["GET /api/users/{id}"] == {"id": [["1", 0.5], ["2", 0.5]]}
    assert "POST /api/transfers" not in params


def test_path_params_several_and_frequency():
    df = requests(
        ("GET", "/api/users/{userId}/accounts/{id}", "/api/users/7/accounts/3", None),
        ("GET", "/api/users/{userId}/accounts/{id}", "/api/users/7/accounts/4", None),
        ("GET", "/api/users/{userId}/accounts/{id}", "/otra/ruta", None),
    )
    params = build_path_params(df)["GET /api/users/{userId}/accounts/{id}"]
    assert params == {"userId": [["7", 1.0]], "id": [["3", 0.5], ["4", 0.5]]}


def test_body_models_numbers_ids_and_choices():
    df = requests(
        ("POST", "/api/transfers", "/api/transfers", {"fromAccountId": 1, "amount": 10.5, "concept": "a"}),
        ("POST", "/api/transfers", "/api/transfers", {"fromAccountId": 2, "amount": 99, "concept": "a"}),
        ("POST", "/api/transfers", "/api/transfers", {"fromAccountId": 1, "amount": 50.25}),
        ("POST", "/api/transfers", "/api/transfers", "no es un objeto"),
    )
    model = build_body_models(df)["POST /api/transfers"]
    assert model["amount"] == {"type": "number", "min": 10.5, "max": 99, "decimals": 2, "presence": 1.0}
    # Los ids se eligen entre los vistos, no de un rango
    assert model["fromAccountId"]["type"] == "choice"
    assert model["fromAccountId"]["values"] == [[1, pytest.approx(2 / 3)], [2, pytest.approx(1 / 3)]]
    assert model["concept"] == {"type": "choice", "values": [["a", 1.0]], "presence": pytest.approx(2 / 3)}


def test_body_models_skip_unsafe_and_nested_values():
    df = requests(
        ("POST", "/api/x", "/api/x", {"meta": {"k": [1, 2]}, "name": "${evil}"}),
        ("POST", "/api/x", "/api/x", {"meta": {"k": [1, 2]}, "name": "ok"}),
    )
    model = build_body_models(df)["POST /api/x"]
    assert model["meta"]["values"] == [[{"k": [1, 2]}, 1.0]]
    # JMeter sustituiría ${...}: ese valor no se incrusta
    assert model["name"]["values"] == [["ok", 1.0]]


def test_no_bodies():
    assert build_body_models(requests(("GET", "/a", "/a", None))) == {}
