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
