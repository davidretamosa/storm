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
