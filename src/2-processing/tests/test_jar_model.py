"""Combinación de logs y .jar (rama 'sencillo'): prior del .jar, bodies desde el DTO y pausas por defecto."""
import pytest

from jar_parser.parser import parse_jar
from log_parser.parser import parse_logs
from main import pause_range
from traffic_model.markov import END, build_markov_model, mix
from traffic_model.payloads import build_body_models
from traffic_model.scaling import DEFAULT_VUSERS, predict_traffic_scale
from traffic_model.think_time import DEFAULT_PAUSE_MS, add_default_pauses, build_think_times

DEMO_JAR = "samples/demo-bankapp.jar"
SAMPLE_LOG = "samples/access_sample.log"


def test_mix_example_from_the_guide():
    # 28 observaciones en los logs + 10 inventadas repartidas entre 5 opciones (2 cada una)
    counts = {"movimientos": 9, "ingresar": 7, "sacar": 6, "transferir": 5, END: 1}
    p = mix(counts, list(counts), jar_weight=10)
    assert p["movimientos"] == pytest.approx(11 / 38)
    assert p[END] == pytest.approx(3 / 38)
    assert sum(p.values()) == pytest.approx(1.0)


def test_mix_without_jar_is_only_logs():
    assert mix({"a": 3, "b": 1}, [], jar_weight=10) == {"a": 0.75, "b": 0.25}


def test_only_jar_everything_equally_likely():
    model = build_markov_model(None, endpoints=parse_jar(DEMO_JAR))
    assert len(model["states"]) == 12
    assert all(p == pytest.approx(1 / 12) for p in model["start"].values())
    for targets in model["transitions"].values():
        assert len(targets) == 13  # las 12 peticiones + END
        assert sum(targets.values()) == pytest.approx(1.0)


def test_logs_and_jar_unused_endpoint_gets_small_probability():
    df = parse_logs(SAMPLE_LOG)
    model = build_markov_model(df, endpoints=parse_jar(DEMO_JAR))
    assert "DELETE /api/accounts/{id}" in model["states"]
    after_account = model["transitions"]["GET /api/accounts/{id}"]
    assert 0 < after_account["DELETE /api/accounts/{id}"] < 0.05
    # Lo que más pasa en los logs sigue siendo lo más probable
    assert max(after_account, key=after_account.get) == "GET /api/accounts/{id}/transactions"


def test_more_jar_weight_moves_towards_uniform():
    df = parse_logs(SAMPLE_LOG)
    endpoints = parse_jar(DEMO_JAR)
    light = build_markov_model(df, endpoints=endpoints, jar_weight=1)
    heavy = build_markov_model(df, endpoints=endpoints, jar_weight=1000)
    request = "GET /api/accounts/{id}"
    assert light["transitions"][request]["DELETE /api/accounts/{id}"] < heavy["transitions"][request]["DELETE /api/accounts/{id}"]
    assert heavy["transitions"][request]["DELETE /api/accounts/{id}"] == pytest.approx(1 / 13, abs=0.01)


def test_jar_weight_zero_does_not_break():
    model = build_markov_model(None, endpoints=parse_jar(DEMO_JAR), jar_weight=0)
    assert all(targets == {END: 1.0} for targets in model["transitions"].values())


def test_bodies_from_dto_only_when_logs_have_none():
    endpoints = parse_jar(DEMO_JAR)
    only_jar = build_body_models(None, endpoints)
    assert only_jar["POST /api/accounts/{id}/deposit"] == {
        "amount": {"type": "number", "min": 1, "max": 100, "decimals": 2, "presence": 1.0}
    }
    assert only_jar["POST /api/transfers"]["fromAccountId"]["type"] == "choice"  # ids: valor fijo, no un rango
    assert only_jar["POST /api/transfers"]["concept"]["values"] == [["test", 1.0]]

    # Con logs, el body de crear cuenta es el de los logs ({"userId": ...}), no el DTO entero
    with_logs = build_body_models(parse_logs(SAMPLE_LOG), endpoints)
    assert set(with_logs["POST /api/accounts"]) == {"userId"}


def test_default_pauses_only_where_there_is_no_data():
    df = parse_logs(SAMPLE_LOG)
    model = build_markov_model(df, endpoints=parse_jar(DEMO_JAR))
    observed = build_think_times(df)
    pauses = add_default_pauses(build_think_times(df), model)
    pair = ("GET /api/users/{id}", "GET /api/accounts/{id}")
    assert pauses[pair[0]][pair[1]] == observed[pair[0]][pair[1]]          # de los logs: no cambia
    assert pauses["GET /api/accounts/{id}"]["DELETE /api/accounts/{id}"] == DEFAULT_PAUSE_MS  # del .jar


def test_pause_range():
    assert pause_range("1-3") == [1000, 1500, 2000, 2500, 3000]
    assert pause_range("0-0") == [0]


def test_scaling_without_logs():
    assert predict_traffic_scale(None)["vusers"] == DEFAULT_VUSERS
