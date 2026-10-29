import pandas as pd

from log_parser.parser import parse_logs


def test_parses_only_valid_requests(log_file):
    df = parse_logs(log_file)
    assert len(df) == 5
    assert list(df["session_id"].unique()) == ["a", "b"]


def test_typed_columns(log_file):
    df = parse_logs(log_file)
    row = df.iloc[3]
    assert (row["method"], row["endpoint"], row["path"]) == ("POST", "/api/transfers", "/api/transfers")
    assert (row["status"], row["duration_ms"], row["user_id"]) == (201, 40, 2)
    assert (row["request_size_bytes"], row["response_size_bytes"]) == (0, 100)
    assert df["timestamp"].is_monotonic_increasing
    assert str(df["timestamp"].dt.tz) == "UTC"


def test_body_only_when_json_object(log_file):
    bodies = parse_logs(log_file)["body"].tolist()
    assert bodies[3] == {"fromAccountId": 1, "amount": 10.5, "concept": "Cena con amigos"}
    # null en los GET y texto en vez de objeto -> sin cuerpo
    assert all(pd.isna(bodies[i]) for i in (0, 1, 2, 4))


def test_empty_file(tmp_path):
    path = tmp_path / "empty.log"
    path.write_text("")
    assert parse_logs(str(path)).empty


def test_sample_log_is_valid():
    df = parse_logs("samples/access_sample.log")
    assert len(df) > 50
    assert df["session_id"].notna().all()
    # Las 11 peticiones de la API (GET y POST de /api/users y /api/accounts cuentan aparte)
    assert len(df.groupby(["method", "endpoint"])) == 11


def test_otel_lines(tmp_path):
    import json

    otel = {
        "timeUnixNano": "1790845200000000000",
        "traceId": "t1",
        "spanId": "s1",
        "attributes": {
            "http.request.method": "POST",
            "http.route": "/api/accounts/{id}/deposit",
            "url.path": "/api/accounts/3/deposit",
            "http.response.status_code": 201,
            "app.request.duration_ms": 12,
            "session.id": "sess-1",
            "user.id": 7,
            "app.request.body": "{\"amount\": 50.5}",
        },
    }
    flat = {"timestamp": "2026-10-01T09:00:00Z", "sessionId": "sess-2", "method": "GET",
            "endpoint": "/api/users/{id}", "path": "/api/users/1", "status": 200, "body": None}
    path = tmp_path / "mixed.log"
    path.write_text(json.dumps(otel) + "\n" + json.dumps(flat) + "\n", encoding="utf-8")

    df = parse_logs(str(path))
    assert len(df) == 2
    by_session = df.set_index("session_id")
    # El de OTel se lee con sus atributos
    assert by_session.loc["sess-1", "endpoint"] == "/api/accounts/{id}/deposit"
    assert by_session.loc["sess-1", "path"] == "/api/accounts/3/deposit"
    assert by_session.loc["sess-1", "status"] == 201
    assert by_session.loc["sess-1", "body"] == {"amount": 50.5}
    # El del formato del proyecto se sigue leyendo igual
    assert by_session.loc["sess-2", "endpoint"] == "/api/users/{id}"
