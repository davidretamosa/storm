import pandas as pd

from log_parser.parser import parse_logs


def test_parses_only_access_lines(log_file):
    df = parse_logs(log_file)
    assert len(df) == 5
    assert list(df["session_id"].unique()) == ["a", "b"]


def test_typed_columns(log_file):
    df = parse_logs(log_file)
    row = df.iloc[3]
    assert (row["method"], row["endpoint"], row["status"], row["duration_ms"]) == ("POST", "/api/transfers", 201, 40)
    assert df["timestamp"].is_monotonic_increasing


def test_empty_file(tmp_path):
    path = tmp_path / "empty.log"
    path.write_text("")
    assert parse_logs(str(path)).empty


def test_quoted_fields_and_path(log_file):
    row = parse_logs(log_file).iloc[1]
    # ua con espacios no rompe el resto de campos
    assert (row["session_id"], row["path"]) == ("b", "/api/users/2")


def test_body_is_last_field_and_may_have_spaces(log_file):
    bodies = parse_logs(log_file)["body"].tolist()
    assert bodies[3] == '{"fromAccountId": 1, "amount": 10.5, "concept": "Cena con amigos"}'
    # sin cuerpo ('-'), recortado por la app ('...') o sin campo cuerpo -> None
    assert all(pd.isna(bodies[i]) for i in (0, 1, 4))
