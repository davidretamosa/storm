import pandas as pd
import pytest

from log_parser.parser import parse_logs
from traffic_model.markov import END, build_markov_model
from traffic_model.scaling import predict_traffic_scale
from traffic_model.think_time import build_think_times


def test_markov_transitions_follow_each_session(log_file):
    transitions = build_markov_model(parse_logs(log_file))["transitions"]
    # a: users -> accounts -> transfers ; b: users -> transfers
    assert transitions["GET /api/users/{id}"] == {"GET /api/accounts/{id}": 0.5, "POST /api/transfers": 0.5}
    assert transitions["GET /api/accounts/{id}"] == {"POST /api/transfers": 1.0}

def test_markov_without_sessions():
    df = pd.DataFrame({
        "timestamp": [1, 2, 3, 4],
        "method": ["GET"] * 4,
        "endpoint": ["/a", "/a", "/a", "/b"],
        "session_id": [None] * 4,
    })

    model = build_markov_model(df)

    # Sin sesiones, se utilizan las frecuencias globales.
    assert model["start"] == {
        "GET /a": 0.75,
        "GET /b": 0.25,
    }

    assert model["states"] == ["GET /a", "GET /b"]

    # Las transiciones son estimadas, no observadas.
    # Se utiliza una probabilidad de END constante del 10%.
    for state in model["states"]:
        assert model["transitions"][state] == pytest.approx({
            "GET /a": 0.675,
            "GET /b": 0.225,
            END: 0.1,
        })

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

    # Los timestamps corresponden al final de las peticiones.
    # La pausa descuenta la duración de la petición siguiente.

    assert think["GET /api/users/{id}"]["GET /api/accounts/{id}"] == [1988] * 5

    assert think["GET /api/accounts/{id}"]["POST /api/transfers"] == [1965] * 5

    assert think["GET /api/users/{id}"]["POST /api/transfers"] == [1960] * 5

    assert "POST /api/transfers" not in think


def test_think_times_are_capped():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-10-01T09:00:00", "2026-10-01T10:00:00"]),
        "method": ["GET", "GET"], "endpoint": ["/a", "/b"], "session_id": ["s", "s"],
    })
    assert build_think_times(df, samples=3, max_ms=5000)["GET /a"]["GET /b"] == [5000] * 3


def test_scaling(log_file):
    profile = predict_traffic_scale(parse_logs(log_file))
    # sesiones a (09:00:01-05) y b (09:00:02-04) coinciden en el tiempo: pico = 2
    assert profile == {"vusers": 2, "ramp_up_seconds": 60, "duration_seconds": 300}


def test_peak_concurrency_not_total_sessions():
    import pandas as pd
    from traffic_model.scaling import peak_concurrent_sessions

    times = pd.to_datetime
    # 3 sesiones una detrás de otra (nunca coinciden) + 2 que coinciden entre ellas
    df = pd.DataFrame({
        "session_id": ["a", "a", "b", "b", "c", "c", "d", "d", "e", "e"],
        "timestamp": times([
            "2026-10-01T09:00:00", "2026-10-01T09:01:00",   # a
            "2026-10-01T10:00:00", "2026-10-01T10:01:00",   # b
            "2026-10-01T11:00:00", "2026-10-01T11:01:00",   # c
            "2026-10-01T12:00:00", "2026-10-01T12:05:00",   # d  ┐ abiertas
            "2026-10-01T12:01:00", "2026-10-01T12:02:00",   # e  ┘ a la vez
        ]),
    })
    assert peak_concurrent_sessions(df) == 2               # 5 sesiones en total, pero como mucho 2 a la vez
    assert predict_traffic_scale(df)["vusers"] == 2        # el pico real


def test_single_request_sessions_count():
    import pandas as pd
    from traffic_model.scaling import peak_concurrent_sessions

    df = pd.DataFrame({"session_id": ["a", "b"], "timestamp": pd.to_datetime(["2026-10-01T09:00:00"] * 2)})
    assert peak_concurrent_sessions(df) == 2


def test_think_time_start_timestamps():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-10-01T09:00:00",
            "2026-10-01T09:00:01"
        ]),
        "method": ["GET", "GET"],
        "endpoint": ["/a", "/b"],
        "session_id": ["s", "s"],
        "duration_ms": [200, 300],
        "timestamp_kind": ["start", "start"],
    })

    think = build_think_times(df, samples=5)

    assert think["GET /a"]["GET /b"] == [800] * 5


def test_think_time_end_timestamps():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-10-01T09:00:00.200",
            "2026-10-01T09:00:01.300"
        ]),
        "method": ["GET", "GET"],
        "endpoint": ["/a", "/b"],
        "session_id": ["s", "s"],
        "duration_ms": [200, 300],
        "timestamp_kind": ["end", "end"],
    })

    think = build_think_times(df, samples=5)

    assert think["GET /a"]["GET /b"] == [800] * 5


def test_think_time_unknown_timestamps():
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-10-01T09:00:00",
            "2026-10-01T09:00:01"
        ]),
        "method": ["GET", "GET"],
        "endpoint": ["/a", "/b"],
        "session_id": ["s", "s"],
        "duration_ms": [200, 300],
        "timestamp_kind": ["unknown", "unknown"],
    })

    think = build_think_times(df, samples=5)

    assert think["GET /a"]["GET /b"] == [1000] * 5

def test_header_distribution():
    import pandas as pd
    from traffic_model.headers import build_header_models

    df = pd.DataFrame({
        "method": ["GET"] * 4,
        "endpoint": ["/api/items"] * 4,
        "headers": [
            {"x-user-id": ["1"]},
            {"x-user-id": ["1"]},
            {"x-user-id": ["2"]},
            {"x-user-id": ["3"]},
        ],
    })

    result = build_header_models(df, ["x-user-id"])

    assert result["GET /api/items"] == [
        [{"x-user-id": ["1"]}, 0.50],
        [{"x-user-id": ["2"]}, 0.25],
        [{"x-user-id": ["3"]}, 0.25],
    ]


def test_header_combinations():
    import pandas as pd
    from traffic_model.headers import build_header_models

    df = pd.DataFrame({
        "method": ["GET", "GET"],
        "endpoint": ["/api/items", "/api/items"],
        "headers": [
            {"x-user-id": ["1"], "accept-language": ["ca"]},
            {"x-user-id": ["2"], "accept-language": ["en"]},
        ],
    })

    result = build_header_models(
        df, ["x-user-id", "accept-language"]
    )

    assert result["GET /api/items"] == [
        [{"x-user-id": ["1"], "accept-language": ["ca"]}, 0.5],
        [{"x-user-id": ["2"], "accept-language": ["en"]}, 0.5],
    ]


def test_header_allowlist():
    import pandas as pd
    from traffic_model.headers import build_header_models

    df = pd.DataFrame({
        "method": ["GET"],
        "endpoint": ["/api/items"],
        "headers": [
            {
                "x-user-id": ["1"],
                "accept-language": ["ca"],
                "authorization": ["Bearer example"],
            }
        ],
    })

    result = build_header_models(
        df, ["x-user-id", "authorization"]
    )

    assert result["GET /api/items"] == [
        [{"x-user-id": ["1"]}, 1.0]
    ]

    assert build_header_models(df) == {}


def test_header_missing_values():
    import pandas as pd
    from traffic_model.headers import build_header_models

    df = pd.DataFrame({
        "method": ["GET", "GET"],
        "endpoint": ["/api/items", "/api/items"],
        "headers": [
            {"x-user-id": ["1"]},
            {},
        ],
    })

    result = build_header_models(df, ["x-user-id"])

    assert result["GET /api/items"] == [
        [{"x-user-id": ["1"]}, 0.5],
        [{}, 0.5],
    ]

def test_resource_singularization():
    from traffic_model.correlation import singularize

    cases = {
        "accounts": "account",
        "products": "product",
        "users": "user",
        "tasks": "task",
        "categories": "category",
        "companies": "company",
        "addresses": "address",
        "boxes": "box",
        "branches": "branch",
        "access": "access",
    }

    for plural, singular in cases.items():
        assert singularize(plural) == singular


def test_correlation_plural_resources():
    from traffic_model.correlation import resource_of_field

    resources = {
        "/api/categories",
        "/api/companies",
        "/api/addresses",
        "/api/products",
        "/api/accounts",
    }

    assert resource_of_field(
        "categoryId", resources
    ) == "/api/categories"

    assert resource_of_field(
        "companyId", resources
    ) == "/api/companies"

    assert resource_of_field(
        "addressId", resources
    ) == "/api/addresses"

    assert resource_of_field(
        "productId", resources
    ) == "/api/products"

    assert resource_of_field(
        "fromAccountId", resources
    ) == "/api/accounts"

    assert resource_of_field(
        "unknownId", resources
    ) is None


def test_body_correlation_with_categories():
    from traffic_model.correlation import build_correlation

    model = {
        "states": [
            "POST /api/categories",
            "POST /api/tasks",
            "GET /api/tasks/{id}",
        ]
    }

    bodies = {
        "POST /api/tasks": {
            "title": {},
            "categoryId": {},
        }
    }

    correlation = build_correlation(model, bodies)

    assert correlation["body_resources"] == {
        "POST /api/tasks": {
            "categoryId": "/api/categories"
        }
    }


def test_markov_partial_sessions():
    import pandas as pd
    from traffic_model.markov import build_markov_model

    df = pd.DataFrame({
        "timestamp": pd.date_range(
            "2026-11-16", periods=6, freq="s"
        ),
        "method": [
            "GET", "GET", "POST", "GET", "GET", "GET"
        ],
        "endpoint": [
            "/api/tasks",
            "/api/products",
            "/api/tasks",
            "/api/customers",
            "/api/categories",
            "/api/tasks"
        ],
        "session_id": [
            "s1", None, "s1", None, "s2", "s2"
        ]
    })

    model = build_markov_model(df)

    assert set(model["states"]) == {
        "GET /api/tasks",
        "POST /api/tasks",
        "GET /api/products",
        "GET /api/customers",
        "GET /api/categories"
    }

    assert model["transitions"]["GET /api/products"] == {
        "END": 1.0
    }

    assert model["transitions"]["GET /api/customers"] == {
        "END": 1.0
    }

    assert model["transitions"]["GET /api/tasks"] == {
        "POST /api/tasks": 0.5,
        "END": 0.5
    }

    assert model["start"] == {
        "GET /api/tasks": 0.25,
        "GET /api/categories": 0.25,
        "GET /api/products": 0.25,
        "GET /api/customers": 0.25
    }

def test_status_transitions_min_probability():
    import pandas as pd
    from traffic_model.markov import build_markov_model

    records = []

    for i in range(10):
        for second, endpoint in [
            (0, "/api/a"),
            (1, "/api/b" if i < 9 else "/api/c")
        ]:
            records.append({
                "timestamp": pd.Timestamp("2026-11-16")
                             + pd.Timedelta(seconds=second),
                "method": "GET",
                "endpoint": endpoint,
                "session_id": f"s{i}",
                "status": 200
            })

    df = pd.DataFrame(records)

    model = build_markov_model(df, min_probability=0.2)

    assert model["transitions"]["GET /api/a"] == {
        "GET /api/b": 1.0
    }

    assert model["status_transitions"]["GET /api/a"]["200"] == {
        "GET /api/b": 1.0
    }

    # Sin umbral se conservan las probabilidades originales
    model = build_markov_model(df, min_probability=0.0)

    assert model["status_transitions"]["GET /api/a"]["200"] == {
        "GET /api/b": 0.9,
        "GET /api/c": 0.1
    }

def test_markov_end_probability_without_sessions():
    import math
    import pandas as pd
    from traffic_model.markov import build_markov_model

    for n in [10, 50, 100, 500, 1000, 10000]:

        df = pd.DataFrame({
            "timestamp": pd.date_range(
                "2026-11-16", periods=n, freq="s"
            ),
            "method": ["GET"] * n,
            "endpoint": ["/api/a", "/api/b"] * (n // 2),
            "session_id": [None] * n
        })

        model = build_markov_model(df)

        for probabilities in model["transitions"].values():

            assert math.isclose(probabilities["END"], 0.1)

            assert math.isclose(
                probabilities["GET /api/a"], 0.45
            )

            assert math.isclose(
                probabilities["GET /api/b"], 0.45
            )

            assert math.isclose(
                sum(probabilities.values()), 1.0
            )

def test_default_pauses_for_status_transitions():
    from traffic_model.think_time import add_default_pauses

    model = {
        "transitions": {
            "GET /api/a": {
                "GET /api/b": 1.0
            }
        },
        "status_transitions": {
            "GET /api/a": {
                "500": {
                    "GET /api/c": 1.0,
                    "END": 0.0
                }
            }
        }
    }

    observed = {
        "GET /api/a": {
            "GET /api/b": [750]
        }
    }

    result = add_default_pauses(
        observed,
        model,
        default_pause_ms=[1000, 2000]
    )

    # Conservar las pausas aprendidas.
    assert result["GET /api/a"]["GET /api/b"] == [750]

    # Añadir pausas a las transiciones condicionadas.
    assert result["GET /api/a"]["GET /api/c"] == [1000, 2000]

    # No añadir pausas para finalizar sesiones.
    assert "END" not in result["GET /api/a"]

def test_think_time_infinite_duration():
    import numpy as np
    import pandas as pd
    from traffic_model.think_time import build_think_times

    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-11-16T10:00:00",
            "2026-11-16T10:00:02"
        ]),
        "method": ["GET", "GET"],
        "endpoint": ["/api/a", "/api/b"],
        "session_id": ["s1", "s1"],
        "timestamp_kind": ["start", "start"],
        "duration_ms": [np.inf, 100.0]
    })

    result = build_think_times(df, samples=1)

    # Una duración infinita no debe eliminar la pausa.
    assert result["GET /api/a"]["GET /api/b"] == [2000]