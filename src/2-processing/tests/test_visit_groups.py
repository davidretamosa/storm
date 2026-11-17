"""Grupos de visita (--visit-groups, T-2.1): la tabla de cada sesión, el KMeans y el plan.

Los logs sintéticos usan endpoints inventados (/a, /b...): la mejora no sabe nada de ninguna app.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

import sklearn.cluster
import sklearn.metrics

from bench.tests.support import BANKAPP, JAR, ROOT, generate, sha256
from log_parser.parser import parse_logs
from traffic_model import visit_groups
from traffic_model.visit_groups import (
    CREATES, LENGTH, MAX_GROUPS, PAUSE, RATE_4XX, SEED, cluster_sessions, describe, find_visit_groups,
    session_table,
)

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def write_log(path, sessions, without_id=()):
    """sessions: [[(método, endpoint, código, segundos desde el inicio de la sesión), ...], ...], una cada minuto.

    Las sesiones de `without_id` (por posición) se escriben sin sessionId, y un código None, sin status.
    """
    lines = []
    for n, requests in enumerate(sessions):
        start = T0 + timedelta(minutes=n)
        for method, endpoint, status, seconds in requests:
            entry = {
                "timestamp": (start + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z"),
                "sessionId": f"s{n}", "userId": 1, "method": method, "endpoint": endpoint, "path": endpoint,
                "status": status, "durationMs": 5, "body": None}
            if n in without_id:
                del entry["sessionId"]
            if status is None:
                del entry["status"]
            lines.append(json.dumps(entry))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def visit(keys, pause, status=200):
    return [(*key.split(" "), status, i * pause) for i, key in enumerate(keys)]


def readers(count):
    """Visitas que solo leen: GET /a -> GET /b, con pausas de 2 a 4 s."""
    return [visit(["GET /a", "GET /b"], 2 + n % 3) for n in range(count)]


def writers(count):
    """Visitas que crean: GET /a -> POST /c -> GET /b -> POST /d, con 201 y pausas de 3 a 6 s."""
    return [visit(["GET /a", "POST /c", "GET /b", "POST /d"], 3 + n % 4, status=201) for n in range(count)]


def two_kinds():
    """30 lectores y 30 que crean, alternados (s0 lector, s1 creador, ...)."""
    return [s for pair in zip(readers(30), writers(30)) for s in pair]


def groups_of(tmp_path, sessions, name="log.jsonl"):
    return find_visit_groups(parse_logs(write_log(tmp_path / name, sessions)))


# --- La tabla de cada sesión ------------------------------------------------------------------------

def test_features_one_row_per_session(tmp_path):
    """Una fila por sesión, con lo que hace, cuánto, la pausa, los 4xx y si crea algo."""
    log = write_log(tmp_path / "log.jsonl", [
        [("GET", "/a", 200, 0), ("GET", "/a", 200, 2), ("POST", "/b", 201, 6)],
        [("GET", "/a", 404, 0)],
    ])
    ids, sequences, matrix, names = session_table(parse_logs(log))

    assert ids == ["s0", "s1"]
    assert sequences == {"s0": ["GET /a", "GET /a", "POST /b"], "s1": ["GET /a"]}
    first = dict(zip(names, matrix[0]))
    assert first["GET /a"] == 2
    assert first["POST /b"] == 1
    assert first[LENGTH] == 3
    assert first[CREATES] == 1
    assert first[PAUSE] == np.log1p(3)
    assert first[RATE_4XX] == 0
    second = dict(zip(names, matrix[1]))
    assert second[RATE_4XX] == 1
    assert second[PAUSE] == 0      # una sola petición: sin pausa
    assert second[CREATES] == 0

    # Orden de aparición (no alfabético: s10 va después de s9) y solo 400-499 es 4xx, solo 201 crea
    codes = [200, 202, 500, 499, 400]
    sessions = [visit(["GET /a"], 1)] * 11 + [[("GET", "/a", code, i) for i, code in enumerate(codes)]]
    ids, _, matrix, names = session_table(parse_logs(write_log(tmp_path / "codes.jsonl", sessions)))
    assert ids == [f"s{n}" for n in range(12)]
    last = dict(zip(names, matrix[-1]))
    assert last[RATE_4XX] == 2 / 5
    assert last[CREATES] == 0


def test_features_without_status_have_no_nan(tmp_path):
    """Sin campo status (o sin la columna), los 4xx y las altas son 0 y no hay ningún NaN."""
    df = parse_logs(write_log(tmp_path / "log.jsonl", [visit(["GET /a", "GET /b"], 2, status=None)] * 3))
    for table in (df, df.drop(columns=["status"])):
        _, _, matrix, names = session_table(table)
        assert not np.isnan(matrix).any()
        assert (matrix[:, names.index(RATE_4XX)] == 0).all()
        assert (matrix[:, names.index(CREATES)] == 0).all()


# --- Logs sin sesiones o mixtos ---------------------------------------------------------------------

def test_no_sessions_makes_no_groups(tmp_path):
    """Un log sin sessionId (o sin log) no hace grupos, y no falla."""
    sessions = two_kinds()
    df = parse_logs(write_log(tmp_path / "log.jsonl", sessions, without_id=range(len(sessions))))
    assert df["session_id"].isna().all()

    for logs in (df, None):
        groups, report = find_visit_groups(logs)
        assert groups == {}
        assert report["sessions"] == 0
        assert report["one_group"] == "el log no tiene sesiones"
        assert describe(report) == "ninguno (el log no tiene sesiones); el plan es el de la cadena"


def test_mixed_log_groups_only_sessions(tmp_path):
    """Las peticiones sin sessionId no entran en el agrupamiento."""
    sessions = two_kinds()
    df = parse_logs(write_log(tmp_path / "log.jsonl", sessions, without_id=range(0, len(sessions), 5)))
    groups, report = find_visit_groups(df)

    expected = set(df["session_id"].dropna())
    assert set(groups) == expected
    assert report["sessions"] == len(expected) == len(sessions) - len(range(0, len(sessions), 5))


# --- El KMeans --------------------------------------------------------------------------------------

def test_cluster_sessions_separates_two_blobs():
    """Dos nubes de puntos bien separadas: k = 2 y cada nube en su grupo, igual en cada llamada."""
    rng = np.random.default_rng(1)
    matrix = np.vstack([rng.normal(0, 0.5, (20, 2)), rng.normal(10, 0.5, (20, 2))])

    labels, k, _ = cluster_sessions(matrix)
    assert k == 2
    assert len(set(labels[:20])) == 1
    assert len(set(labels[20:])) == 1
    assert labels[0] != labels[20]
    again, _, _ = cluster_sessions(matrix)
    assert list(again) == list(labels)

    noise = rng.normal(0, 1, (200, 5))
    assert list(cluster_sessions(noise)[0]) == list(cluster_sessions(noise)[0])

    # Sin StandardScaler, el KMeans partiría por la columna de ruido (escala 100) y no por la que separa (0 / 0,1)
    small = np.repeat([0.0, 0.1], 20) + rng.normal(0, 0.001, 40)
    scaled_matters = np.column_stack([small, rng.normal(0, 100, 40)])
    labels, k, _ = cluster_sessions(scaled_matters, max_groups=2)
    assert k == 2
    assert len(set(labels[:20])) == 1 and len(set(labels[20:])) == 1 and labels[0] != labels[20]


def test_cluster_sessions_picks_the_best_silhouette(tmp_path, monkeypatch):
    """Se prueban todas las k de 2 a top y se elige la de más silueta (la más pequeña si empatan)."""
    assert (SEED, MAX_GROUPS, visit_groups.KMEANS_RUNS, visit_groups.SILHOUETTE_SAMPLE) == (0, 8, 10, 3000)
    _, _, matrix, _ = session_table(parse_logs(write_log(tmp_path / "log.jsonl", two_kinds())))
    top = min(MAX_GROUPS, len(np.unique(matrix, axis=0)), len(matrix) - 1)

    _, k, silhouettes = cluster_sessions(matrix)
    assert list(silhouettes) == list(range(2, top + 1))
    assert all(-1 <= value <= 1 for value in silhouettes.values())
    best = max(silhouettes.values())
    assert k == min(key for key, value in silhouettes.items() if value == best)

    # Empate forzado (misma silueta para todas las k): la k más pequeña. Y la muestra de la silueta:
    # con más filas que SILHOUETTE_SAMPLE, una muestra fija; con menos, todas.
    calls = []
    kmeans = []

    class Spy(sklearn.cluster.KMeans):
        def __init__(self, **kwargs):
            kmeans.append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(sklearn.cluster, "KMeans", Spy)

    def flat(scaled, labels, sample_size=None, random_state=None):
        calls.append((len(scaled), sample_size, random_state))
        return 0.5

    monkeypatch.setattr(sklearn.metrics, "silhouette_score", flat)
    assert cluster_sessions(matrix)[1] == 2
    assert all(call == (len(matrix), None, SEED) for call in calls)
    assert kmeans == [{"n_clusters": k, "n_init": 10, "random_state": SEED} for k in range(2, top + 1)]
    calls.clear()
    monkeypatch.setattr(visit_groups, "SILHOUETTE_SAMPLE", len(matrix))   # n == muestra: todas las filas
    cluster_sessions(matrix)
    assert calls and all(call == (len(matrix), None, SEED) for call in calls)
    calls.clear()
    monkeypatch.setattr(visit_groups, "SILHOUETTE_SAMPLE", len(matrix) - 1)
    cluster_sessions(matrix)
    assert all(call == (len(matrix), len(matrix) - 1, SEED) for call in calls)


def test_two_clear_kinds_are_never_mixed(tmp_path):
    """Lectores y creadores nunca caen en el mismo grupo. No se fija k = 2: con pausas discretas la silueta
    puede preferir una k mayor (la regla 1 del T-2.2 junta los grupos que navegan igual)."""
    groups, report = groups_of(tmp_path, two_kinds())

    assert report["k"] >= 2
    assert "one_group" not in report
    kinds = {}
    for session, group in groups.items():
        kinds.setdefault(group, set()).add("reader" if int(session[1:]) % 2 == 0 else "writer")
    assert all(len(found) == 1 for found in kinds.values())
    assert describe(report) == f"{report['k']} ({', '.join(map(str, report['sizes']))} sesiones)"


def test_identical_sessions_are_one_group(tmp_path):
    """15 sesiones idénticas: un solo grupo, sin KMeans."""
    groups, report = groups_of(tmp_path, [visit(["GET /a", "GET /b"], 2)] * 15)

    assert report["k"] == 1
    assert set(groups.values()) == {0}
    assert len(groups) == 15
    assert report["one_group"] == "todas las sesiones son iguales"
    assert describe(report) == f"1 ({report['one_group']}); el plan es el de la cadena"

    for few in ([visit(["GET /a"], 1)], [visit(["GET /a"], 1), visit(["GET /b", "POST /c"], 9, status=404)]):
        groups, report = groups_of(tmp_path, few, f"few{len(few)}.jsonl")
        assert report["k"] == 1
        assert set(groups.values()) == {0}
        assert len(groups) == len(few)


def test_same_log_same_groups(tmp_path):
    """El mismo log da siempre los mismos grupos."""
    assert groups_of(tmp_path, two_kinds(), "a.jsonl") == groups_of(tmp_path, two_kinds(), "b.jsonl")


def test_groups_numbered_by_size(tmp_path):
    """El grupo 0 es el más grande: con 40 lectores y 20 creadores, solo tiene lectores. Los creadores van
    primero en el log, para que el grupo que aparece antes no sea el más grande."""
    groups, report = groups_of(tmp_path, writers(20) + readers(40))

    members = [int(session[1:]) for session, group in groups.items() if group == 0]
    assert members and all(n >= 20 for n in members)
    assert report["sizes"][0] == max(report["sizes"]) == len(members)
    assert report["sizes"] == sorted(report["sizes"], reverse=True)

    # Si dos grupos tienen el mismo tamaño, va antes el que aparece antes en el log
    first = {}
    for session, group in groups.items():
        first[group] = min(first.get(group, len(groups)), int(session[1:]))
    sizes = report["sizes"]
    ties = [(g, h) for g in range(len(sizes)) for h in range(g + 1, len(sizes)) if sizes[g] == sizes[h]]
    assert ties
    assert all(first[g] < first[h] for g, h in ties)


# --- El plan ----------------------------------------------------------------------------------------

def test_plan_without_sessions_is_the_chain_plan(tmp_path):
    """Sin sesiones (log sin sessionId, o solo --jar), --visit-groups deja el plan como el de la cadena."""
    sessions = two_kinds()
    log = str(write_log(tmp_path / "log.jsonl", sessions, without_id=range(len(sessions))))

    for inputs in (["--logs", log], ["--jar", JAR]):
        plain = generate(inputs, tmp_path / "plain.jmx")
        grouped = generate([*inputs, "--visit-groups"], tmp_path / "grouped.jmx")
        assert sha256(plain) == sha256(grouped)

    # Sin el flag, main.py no carga scikit-learn, no escribe nada en stderr ni crea otros ficheros; con el
    # flag, la salida es la misma más una sola línea "Grupos de visita: ..."
    script = ("import runpy, sys; sys.argv = ['main.py', *sys.argv[1:]]; runpy.run_path('main.py', run_name='__main__'); "
              "print('SKLEARN', any(name.split('.')[0] == 'sklearn' for name in sys.modules))")

    def run(inputs, folder):
        folder.mkdir()
        result = subprocess.run([sys.executable, "-c", script, *inputs, "--output", str(folder / "plan.jmx")],
                                cwd=ROOT, env={**os.environ, "PYTHONHASHSEED": "0"}, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stderr == "", result.stderr
        assert [path.name for path in folder.iterdir()] == ["plan.jmx"]
        return result.stdout.replace(str(folder), "<out>").splitlines()

    for n, inputs in enumerate((["--logs", BANKAPP, "--session"], ["--jar", JAR], ["--logs", log])):
        off = run(inputs, tmp_path / f"off{n}")
        on = run([*inputs, "--visit-groups"], tmp_path / f"on{n}")
        assert "SKLEARN False" in off
        assert not any("Grupos de visita" in line for line in off)
        extra = [line for line in on if line.startswith("Grupos de visita: ")]
        assert len(extra) == 1
        assert [line for line in on if line != extra[0] and not line.startswith("SKLEARN")] == \
               [line for line in off if not line.startswith("SKLEARN")]


def test_flag_does_not_change_the_plan_yet(tmp_path):
    """PROVISIONAL (lo borra el T-2.4): con grupos, el .jmx aún no cambia."""
    plain = generate(["--logs", BANKAPP, "--session"], tmp_path / "plain.jmx")
    grouped = generate(["--logs", BANKAPP, "--session", "--visit-groups"], tmp_path / "grouped.jmx")
    assert sha256(plain) == sha256(grouped)
