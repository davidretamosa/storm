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

def test_otel_list_attributes(tmp_path):
    import json

    otel = {
        "startTimeUnixNano": "1790845200000000000",
        "spanId": "s1",
        "attributes": [
            {
                "key": "http.request.method",
                "value": {"stringValue": "GET"},
            },
            {
                "key": "http.route",
                "value": {"stringValue": "/employees/{id}"},
            },
            {
                "key": "url.path",
                "value": {"stringValue": "/employees/3"},
            },
            {
                "key": "http.response.status_code",
                "value": {"intValue": "200"},
            },
        ],
    }

    path = tmp_path / "otel.log"
    path.write_text(json.dumps(otel) + "\n", encoding="utf-8")

    df = parse_logs(str(path))

    assert len(df) == 1
    assert df.iloc[0]["method"] == "GET"
    assert df.iloc[0]["endpoint"] == "/employees/{id}"
    assert df.iloc[0]["path"] == "/employees/3"
    assert df.iloc[0]["status"] == 200

def test_otlp_export(tmp_path):
    import json

    http_span = {
        "kind": 2,
        "startTimeUnixNano": "1790845200000000000",
        "spanId": "s1",
        "attributes": [
            {
                "key": "http.request.method",
                "value": {"stringValue": "GET"},
            },
            {
                "key": "http.route",
                "value": {"stringValue": "/employees"},
            },
        ],
    }

    internal_span = {
        **http_span,
        "kind": 3,
        "spanId": "s2",
    }

    export = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [http_span, internal_span]
                    }
                ]
            }
        ]
    }

    path = tmp_path / "traces.json"
    path.write_text(json.dumps(export), encoding="utf-8")

    df = parse_logs(str(path))

    assert len(df) == 1
    assert df.iloc[0]["method"] == "GET"
    assert df.iloc[0]["endpoint"] == "/employees"
    assert df.iloc[0]["request_id"] == "s1"

def test_otel_trace_is_not_session(tmp_path):
    import json

    otel = {
        "startTimeUnixNano": "1790845200000000000",
        "traceId": "trace-123",
        "spanId": "span-123",
        "attributes": {
            "http.request.method": "GET",
            "http.route": "/employees",
        },
    }

    path = tmp_path / "otel.log"
    path.write_text(json.dumps(otel), encoding="utf-8")

    df = parse_logs(str(path))

    assert len(df) == 1
    assert df.iloc[0]["request_id"] == "span-123"
    assert pd.isna(df.iloc[0]["session_id"])

def test_otel_query_params():
    from log_parser.otel import parse_otel_record

    record = {
        "timestamp": "2026-11-15T10:00:00Z",
        "attributes": {
            "http.request.method": "GET",
            "http.route": "/api/products",
            "url.path": "/api/products",
            "url.query": "page=0&size=5",
        },
    }

    row = parse_otel_record(record)

    assert row["endpoint"] == "/api/products"
    assert row["path"] == "/api/products"
    assert row["query"] == "page=0&size=5"


def test_otel_legacy_query_params():
    from log_parser.otel import parse_otel_record

    record = {
        "timestamp": "2026-11-15T10:00:00Z",
        "attributes": {
            "http.method": "GET",
            "http.target": "/api/products?page=0&size=5",
        },
    }

    row = parse_otel_record(record)

    assert row["endpoint"] == "/api/products"
    assert row["path"] == "/api/products"
    assert row["query"] == "page=0&size=5"


def test_json_query_params():
    import json
    from log_parser.parser import parse_line

    record = {
        "timestamp": "2026-11-15T10:00:00Z",
        "method": "GET",
        "endpoint": "/api/products",
        "path": "/api/products?page=0&size=5",
    }

    row = parse_line(json.dumps(record))

    assert row["endpoint"] == "/api/products"
    assert row["path"] == "/api/products"
    assert row["query"] == "page=0&size=5"

def test_otlp_span_duration():
    from log_parser.otel import parse_otel_record

    record = {
        "startTimeUnixNano": "1794766173000000000",
        "endTimeUnixNano": "1794766173200000000",
        "attributes": {
            "http.request.method": "GET",
            "http.route": "/api/employees"
        }
    }

    row = parse_otel_record(record)

    assert row["duration_ms"] == 200.0


def test_otel_custom_duration():
    from log_parser.otel import parse_otel_record

    record = {
        "startTimeUnixNano": "1794766173000000000",
        "endTimeUnixNano": "1794766173200000000",
        "attributes": {
            "http.request.method": "GET",
            "http.route": "/api/employees",
            "app.request.duration_ms": 150
        }
    }

    row = parse_otel_record(record)

    assert row["duration_ms"] == 150


def test_otel_missing_duration():
    from log_parser.otel import parse_otel_record

    record = {
        "startTimeUnixNano": "1794766173000000000",
        "attributes": {
            "http.request.method": "GET",
            "http.route": "/api/employees"
        }
    }

    row = parse_otel_record(record)

    assert row["duration_ms"] is None

def test_otel_request_headers():
    from log_parser.otel import parse_otel_record

    record = {
        "timestamp": "2026-11-15T10:00:00Z",
        "attributes": [
            {
                "key": "http.request.method",
                "value": {"stringValue": "GET"}
            },
            {
                "key": "http.route",
                "value": {"stringValue": "/api/items"}
            },
            {
                "key": "http.request.header.x-user-id",
                "value": {
                    "arrayValue": {
                        "values": [
                            {"stringValue": "123"}
                        ]
                    }
                }
            }
        ]
    }

    row = parse_otel_record(record)

    assert row["headers"] == {
        "x-user-id": ["123"]
    }


def test_normalize_headers():
    from log_parser.headers import normalize_headers

    headers = {
        "X-User-Id": "123",
        "Accept-Language": ["ca", "en"]
    }

    assert normalize_headers(headers) == {
        "x-user-id": ["123"],
        "accept-language": ["ca", "en"]
    }


def test_filter_sensitive_headers():
    from log_parser.headers import normalize_headers

    headers = {
        "Authorization": "Bearer example",
        "Cookie": "session=123",
        "X-Api-Key": "example",
        "Content-Length": "100",
        "X-Tenant-Id": "5"
    }

    assert normalize_headers(headers) == {
        "x-tenant-id": ["5"]
    }


def test_missing_headers():
    from log_parser.headers import normalize_headers

    assert normalize_headers(None) == {}
    assert normalize_headers({}) == {}

def test_invalid_timestamps(tmp_path):
    from log_parser.parser import parse_logs

    path = tmp_path / "logs.jsonl"

    path.write_text(
        '{"timestamp":"2026-11-16T10:00:00Z",'
        '"method":"GET","endpoint":"/api/tasks"}\n'
        '{"timestamp":"invalid-date",'
        '"method":"GET","endpoint":"/api/tasks"}\n'
    )

    df = parse_logs(path)

    assert len(df) == 1
    assert df["timestamp"].notna().all()


def test_invalid_required_field_types(tmp_path):
    import json
    from log_parser.parser import parse_logs

    valid = {
        "timestamp": "2026-11-16T10:00:00Z",
        "method": "GET",
        "endpoint": "/api/tasks"
    }

    records = [
        valid,
        {**valid, "endpoint": 123},
        {**valid, "endpoint": ["/api/tasks"]},
        {**valid, "method": 42},
        {**valid, "timestamp": {}},
        {**valid, "endpoint": "   "}
    ]

    path = tmp_path / "logs.jsonl"
    path.write_text(
        "\n".join(json.dumps(r) for r in records)
    )

    df = parse_logs(path)

    assert len(df) == 1
    assert df.iloc[0]["endpoint"] == "/api/tasks"


def test_invalid_otel_timestamp():
    from log_parser.otel import parse_otel_record

    record = {
        "startTimeUnixNano": {"value": 123},
        "attributes": {
            "http.request.method": "GET",
            "http.route": "/api/tasks"
        }
    }

    assert parse_otel_record(record) is None


def test_invalid_otel_field_types():
    from log_parser.otel import parse_otel_record

    record = {
        "timestamp": "2026-11-16T10:00:00Z",
        "attributes": {
            "http.request.method": "GET",
            "http.route": "/api/tasks"
        }
    }

    for key, value in [
        ("http.request.method", 42),
        ("http.route", 123)
    ]:
        invalid = {
            **record,
            "attributes": {
                **record["attributes"],
                key: value
            }
        }

        assert parse_otel_record(invalid) is None

    invalid_path = {
        **record,
        "attributes": {
            **record["attributes"],
            "url.path": 123
        }
    }

    row = parse_otel_record(invalid_path)

    assert row["path"] == "/api/tasks"


def test_malformed_otlp_structure():
    from log_parser.otel import parse_otlp_export

    valid_span = {
        "kind": 2,
        "startTimeUnixNano": "1794823200000000000",
        "attributes": {
            "http.request.method": "GET",
            "http.route": "/api/tasks"
        }
    }

    assert parse_otlp_export(
        {"resourceSpans": None}
    ) == []

    record = {
        "resourceSpans": [
            None,
            {"scopeSpans": None},
            {
                "scopeSpans": [
                    None,
                    {"spans": None},
                    {"spans": [None, valid_span]}
                ]
            }
        ]
    }

    rows = parse_otlp_export(record)

    assert len(rows) == 1
    assert rows[0]["endpoint"] == "/api/tasks"