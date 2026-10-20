"""El banc de proves: mètriques, servidor eco i instrumentació. scipy només fa falta aquí."""
import json
import subprocess
import sys
import time
import urllib.request

import pandas as pd
import pytest

from ai import jmx_post
from ai.bench import jmeter
from ai.bench.bankapp import free_port
from ai.bench.echo_server import BENCH_HEADER
from ai.bench.run import instrument
from ai.tests.support import AI, INPUTS, LOG, ROOT, generate
from log_parser.parser import parse_logs

pytest.importorskip("scipy")
from ai.bench import metrics  # noqa: E402


def log_df(rows):
    lines = [json.dumps({"timestamp": t, "sessionId": s, "method": m, "endpoint": e, "path": e, "status": 200})
             for t, s, m, e in rows]
    df = pd.DataFrame([json.loads(line) for line in lines])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.rename(columns={"sessionId": "session_id"})


def test_identical_traffic_has_zero_distance():
    df = parse_logs(str(ROOT / LOG))
    result = metrics.fidelity(df, df)
    assert result["endpoint_js"] == pytest.approx(0, abs=1e-6)
    assert result["sequence_js"] == pytest.approx(0, abs=1e-6)
    assert result["pauses"]["wasserstein"] == pytest.approx(0)
    assert result["session_length"]["ks"] == pytest.approx(0)


def test_disjoint_endpoints_have_distance_one():
    a = log_df([("2026-10-01T09:00:00Z", "s", "GET", "/a"), ("2026-10-01T09:00:01Z", "s", "GET", "/a")])
    b = log_df([("2026-10-01T09:00:00Z", "s", "GET", "/b"), ("2026-10-01T09:00:01Z", "s", "GET", "/b")])
    assert metrics.endpoint_distance(metrics.requests(a), metrics.requests(b)) == pytest.approx(1)


def test_pauses_and_sessions():
    df = metrics.requests(log_df([
        ("2026-10-01T09:00:00Z", "a", "GET", "/x"), ("2026-10-01T09:00:10Z", "a", "GET", "/y"),
        ("2026-10-01T09:00:05Z", "b", "GET", "/x"), ("2026-10-01T09:00:35Z", "b", "GET", "/x"),
        ("2026-10-01T09:00:40Z", "b", "GET", "/y"), ("2026-10-01T09:00:41Z", None, "GET", "/z"),
    ]))
    assert sorted(metrics.pauses(df)) == [5, 10, 30]
    assert sorted(metrics.session_lengths(df)) == [2, 3]
    assert metrics.concurrent_sessions(df)["peak"] == 2
    assert metrics.bigrams(df)[("GET /x", "GET /y")] == 2


def test_ignore_removes_the_login():
    df = log_df([("2026-10-01T09:00:00Z", "a", "POST", "/api/sessions"), ("2026-10-01T09:00:01Z", "a", "GET", "/x")])
    assert list(metrics.requests(df, ["POST /api/sessions"])["key"]) == ["GET /x"]


def test_confidence_interval():
    ci = metrics.confidence_interval([1.0, 2.0, 3.0, 4.0, 5.0])
    assert ci["mean"] == 3 and ci["low"] < 3 < ci["high"] and ci["n"] == 5
    assert metrics.confidence_interval([float("nan")])["n"] == 0


def test_acceptance_counts_2xx():
    jtl = pd.DataFrame({"label": ["a", "a", "b"], "responseCode": ["200", "400", "201"]})
    result = metrics.acceptance(jtl)
    assert result["total"] == pytest.approx(200 / 3)
    assert result["by_sampler"]["a"]["pct_2xx"] == 50


def test_echo_server_log_is_readable_by_parse_logs(tmp_path):
    port, out = free_port(), tmp_path / "rebut.jsonl"
    server = subprocess.Popen([sys.executable, "-m", "ai.bench.echo_server", "--out", str(out), "--port", str(port),
                               "--logs", LOG], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/users/7", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/transfers", method="POST",
                                         data=b'{"amount": 5}', headers={BENCH_HEADER: "3-2",
                                                                         "Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=2)
    finally:
        server.terminate()
        server.wait(timeout=10)
    df = parse_logs(str(out))
    assert list(df["method"] + " " + df["endpoint"]) == ["GET /api/users/{id}", "POST /api/transfers"]
    assert df["session_id"].iloc[1] == "3-2" and df["body"].iloc[1] == {"amount": 5}
    assert list(df["status"]) == [200, 201]


def test_instrument_only_adds_the_bench_header(reference_plans, tmp_path):
    plan = reference_plans["logs+jar+session"]
    bench = tmp_path / "banc.jmx"
    instrument(plan, bench)
    root = jmx_post.read(bench).getroot()
    managers = [m for m in root.iter("HeaderManager") if m.get("testname") == "STORM-IA banc: sessió"]
    assert len(managers) == 1
    thread_tree = jmx_post.child_tree(root, root.find(".//ThreadGroup"))
    first, second = list(thread_tree)[:2]
    assert first is managers[0] and second.tag == "hashTree"
    thread_tree.remove(first)
    thread_tree.remove(second)
    import xml.etree.ElementTree as ET
    assert jmx_post.canonical(ET.tostring(root, encoding="unicode")) == jmx_post.canonical(plan)


@pytest.mark.skipif(not jmeter.jmeter_binary().exists(), reason="no hi ha JMeter local")
def test_real_jmeter_accepts_post_processed_plans(tmp_path):
    """Que sigui XML vàlid no vol dir que JMeter l'accepti: el canari i el pla instrumentat, a un JMeter real."""
    canary = generate(AI, ["--ai-canary", *INPUTS["logs+jar+session"]], tmp_path / "canari.jmx")
    bench = tmp_path / "banc.jmx"
    instrument(canary, bench)
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "ai.bench.echo_server", "--out", str(tmp_path / "r.jsonl"),
                               "--port", str(port), "--logs", LOG], cwd=ROOT,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        code, output = jmeter.run(bench, tmp_path / "r.jtl", tmp_path / "j.log",
                                  {"host": "127.0.0.1", "port": port, "duration": 4, "rampup": 1, "vusers": 2})
    finally:
        server.terminate()
        server.wait(timeout=10)
    assert code == 0, output
    assert "Err:     0" in output or "Err: 0" in output.replace("  ", " "), output
    jtl = jmeter.read_jtl(tmp_path / "r.jtl")
    assert len(jtl) > 0 and jtl["success"].all()
