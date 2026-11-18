"""Grupos de visita (--visit-groups): la tabla de cada sesión, el KMeans y el plan (T-2.1), las tres reglas
que juntan y validan los grupos (T-2.2), el modelo de cada grupo (T-2.3) y el selector de grupo del .jmx (T-2.4).

Los logs sintéticos usan endpoints inventados (/a, /b...): la mejora no sabe nada de ninguna app.
"""
import copy
import json
import math
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

import sklearn.cluster
import sklearn.metrics

from bench.jmeter import jmeter_binary
from bench.tests.support import BANKAPP, JAR, ROOT, generate, sha256
from jmx_generator.generator import CHUNK, GROUP_KEYS, TEMPLATES_DIR, _groovy_text, generate_jmx
from log_parser.parser import parse_logs
from main import pause_range
from traffic_model import visit_groups
from traffic_model.markov import END, build_markov_model, build_status_transitions
from traffic_model.think_time import DEFAULT_PAUSE_MS, add_default_pauses, build_think_times
from traffic_model.visit_groups import (
    CREATES, FLOOR, FOLDS, LENGTH, MAX_GROUPS, MIN_GROUP, MIN_STATUS_CASES, PAUSE, RATE_4XX, SAME_NAVIGATION,
    SEED, START, build_group_models, cluster_sessions, describe, describe_models, find_visit_groups,
    group_labels, heldout_gain, js_distance, keep_frequent_statuses, log_likelihood, merge_alike, navigation,
    session_table, split, status_cases,
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


def two_kinds(shared=True):
    """30 lectores y 30 que crean, alternados (s0 lector, s1 creador, ...).

    Con `shared`, los dos pasan por los mismos estados (/a y /b) y una sola cadena los mezcla (genera
    GET /a -> GET /b -> POST /d, que no hace nadie); sin, no comparten ninguna petición."""
    if shared:
        others = writers(30)
    else:
        others = [visit(["POST /c", "GET /d", "POST /c"], 3 + n % 4, status=201) for n in range(30)]
    return [s for pair in zip(readers(30), others) for s in pair]


def one_kind_two_paces():
    """60 visitas que navegan igual (GET /a -> GET /b -> GET /c), unas rápidas (1 s) y otras lentas (60 s)."""
    return [visit(["GET /a", "GET /b", "GET /c"], 1 if n % 2 else 60) for n in range(60)]


def one_random_chain(n=400, seed=1):
    """Visitas de una sola cadena al azar: un solo tipo, pero con secuencias muy distintas (el control de la
    consultora: el KMeans encuentra grupos que no existen)."""
    rng = np.random.default_rng(seed)
    keys = ["GET /a", "GET /b", "POST /c"]
    sessions = []
    for _ in range(n):
        sequence = [keys[rng.integers(3)]]
        while rng.random() < 0.6 and len(sequence) < 12:
            sequence.append(keys[rng.integers(3)])
        sessions.append(visit(sequence, 2))
    return sessions


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
    puede preferir una k mayor (la regla 1 del T-2.2 junta los grupos que navegan igual, y el texto da los
    grupos que quedan, no la k)."""
    groups, report = groups_of(tmp_path, two_kinds())

    assert report["k"] >= 2
    assert "one_group" not in report
    kinds = {}
    for session, group in groups.items():
        kinds.setdefault(group, set()).add("reader" if int(session[1:]) % 2 == 0 else "writer")
    assert all(len(found) == 1 for found in kinds.values())
    assert describe(report) == f"{len(report['sizes'])} ({', '.join(map(str, report['sizes']))} sesiones)"


def test_identical_sessions_are_one_group(tmp_path):
    """15 sesiones idénticas: un solo grupo, sin KMeans."""
    groups, report = groups_of(tmp_path, [visit(["GET /a", "GET /b"], 2)] * 15)

    assert report["k"] == 1
    assert set(groups.values()) == {0}
    assert len(groups) == 15
    assert report["one_group"] == "todas las sesiones son iguales"
    assert describe(report) == f"1 ({report['one_group']}); el plan es el de la cadena"

    # Con 1 o 2 sesiones (diferentes) no se agrupa: son menos de 2 * FOLDS (T-2.2)
    for few in ([visit(["GET /a"], 1)], [visit(["GET /a"], 1), visit(["GET /b", "POST /c"], 9, status=404)]):
        groups, report = groups_of(tmp_path, few, f"few{len(few)}.jsonl")
        assert "k" not in report
        assert report["one_group"] == f"demasiado pocas sesiones ({len(few)}) para validar grupos"
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

    # Si dos grupos tienen el mismo tamaño, va antes el que aparece antes en el log: 30 creadores (primero)
    # y 30 lectores quedan en dos grupos de 30 tras las reglas, y el 0 es el de los creadores
    groups, report = groups_of(tmp_path, writers(30) + readers(30), "ties.jsonl")
    assert report["sizes"] == [30, 30]
    assert {session for session, group in groups.items() if group == 0} == {f"s{n}" for n in range(30)}


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


# --- Las tres reglas (T-2.2) ------------------------------------------------------------------------

def gate_text():
    return "los grupos no predicen mejor las visitas nuevas que un solo modelo"


def hand_gain(df, fold=0):
    """La ganancia de un trozo, a mano con la fórmula del encargo: la media, en las sesiones de prueba, de la
    mezcla (logaddexp de log(peso) + log P según cada grupo) menos log P según una sola cadena."""
    ids, sequences, _, _ = session_table(df)
    train, test = split(ids)[fold]
    labels, _ = group_labels(df, train)
    one = visit_groups.build_markov_model(df[df["session_id"].isin(train)])
    parts = []
    for group in sorted(set(labels.values())):
        members = [s for s in train if labels[s] == group]
        parts.append((len(members) / len(train), visit_groups.build_markov_model(df[df["session_id"].isin(members)])))
    return np.mean([
        np.logaddexp.reduce([np.log(w) + log_likelihood(sequences[s], m) for w, m in parts])
        - log_likelihood(sequences[s], one)
        for s in test])


def test_js_distance_known_values():
    """Jensen-Shannon en base 2 con la raíz (como scipy): 0 si se reparten igual, 1 sin nada en común, y
    {x: 1} contra {x: 1, y: 1} da √0,311278 (calculado a mano). Y los pares que cuenta navigation()."""
    assert js_distance(Counter(x=1, y=3), Counter(x=2, y=6)) == pytest.approx(0, abs=1e-12)
    assert js_distance(Counter(x=1), Counter(y=5)) == pytest.approx(1, abs=1e-12)
    assert js_distance(Counter(x=1), Counter(x=1, y=1)) == pytest.approx(0.55792, abs=1e-5)
    assert js_distance(Counter(x=1), Counter(x=1, y=1)) == pytest.approx(math.sqrt(0.311278), abs=1e-6)
    assert js_distance(Counter(x=1, y=1), Counter(x=1)) == js_distance(Counter(x=1), Counter(x=1, y=1))

    assert navigation([["GET /a", "GET /b"], ["GET /a"]]) == Counter({
        (START, "GET /a"): 2, ("GET /a", "GET /b"): 1, ("GET /b", END): 1, ("GET /a", END): 1})


def test_one_kind_with_two_paces_merges_into_one_group(tmp_path):
    """Regla 1: partir por la pausa no cambia la navegación; los grupos se juntan en uno."""
    groups, report = groups_of(tmp_path, one_kind_two_paces())

    assert set(groups.values()) == {0}
    assert any(merge["why"] == "navegan igual" for merge in report["merges"])
    assert all(merge["js"] < visit_groups.SAME_NAVIGATION for merge in report["merges"])
    assert report["one_group"] == "los grupos navegan igual"
    assert "heldout_gain" not in report


def test_groups_too_small_to_validate_are_merged(tmp_path):
    """Regla 2: una visita rara (2 sesiones) no puede ser un grupo: no quedan sesiones para probarla."""
    odd = [visit(["DELETE /z", "GET /a", "DELETE /z", "GET /b"], 1)] * 2
    groups, report = groups_of(tmp_path, two_kinds() + odd)

    sizes = Counter(groups.values())
    assert len(sizes) == 2
    assert min(sizes.values()) >= MIN_GROUP
    assert any(merge["why"].startswith("demasiado pequeño") for merge in report["merges"])
    assert any(merge["why"] == "demasiado pequeño (2 sesiones)" for merge in report["merges"])
    # Las dos raras van con algún grupo, sin romper los lectores ni los creadores
    assert groups["s60"] == groups["s61"]
    assert len({groups[f"s{n}"] for n in range(0, 60, 2)}) == 1
    assert len({groups[f"s{n}"] for n in range(1, 60, 2)}) == 1

    # Si queda un solo grupo y hay fusiones de las dos reglas, el motivo lo dice
    groups, report = groups_of(tmp_path, one_kind_two_paces() + odd, "both.jsonl")
    whys = {merge["why"] for merge in report["merges"]}
    assert "navegan igual" in whys and "demasiado pequeño (2 sesiones)" in whys
    assert set(groups.values()) == {0}
    assert report["one_group"] == "los grupos navegan igual o son demasiado pequeños"


def test_folds_partition_the_sessions():
    """5 trozos: en cada uno, ninguna sesión está en el entrenamiento y en la prueba a la vez, y cada sesión
    está en la prueba de un solo trozo."""
    ids = [f"s{n}" for n in range(23)]
    folds = split(ids, seed=SEED)

    assert len(folds) == FOLDS == 5
    for train, test in folds:
        assert not set(train) & set(test)
        assert sorted(train + test) == sorted(ids)
    tested = [session for _, test in folds for session in test]
    assert sorted(tested) == sorted(ids)
    assert len(tested) == len(set(tested))
    assert split(ids, seed=SEED) == folds

    # La fórmula del encargo: order = permutación con la semilla % folds; la prueba del trozo f, order == f
    order = np.random.default_rng(SEED).permutation(len(ids)) % FOLDS
    for f, (train, test) in enumerate(folds):
        assert test == [session for session, o in zip(ids, order) if o == f]
        assert train == [session for session, o in zip(ids, order) if o != f]
    assert split(ids) == folds
    assert split(ids, seed=1) != folds


def test_gate_never_trains_on_the_visits_it_tests(tmp_path, monkeypatch):
    """La puerta agrupa cada trozo solo con sus sesiones de entrenamiento (si entraran las de prueba, los
    grupos se validarían a sí mismos)."""
    df = parse_logs(write_log(tmp_path / "log.jsonl", two_kinds()))
    ids = session_table(df)[0]
    trained = []
    original = visit_groups.group_labels

    seeds = []

    def recorder(df, ids, seed=SEED):
        trained.append(set(ids))
        seeds.append(seed)
        return original(df, ids, seed)

    monkeypatch.setattr(visit_groups, "group_labels", recorder)
    gains = heldout_gain(df, ids, {})

    folds = split(ids, SEED)
    assert len(gains) == len(trained) == 5
    for seen, (train, test) in zip(trained, folds):
        assert seen == set(train)
        assert not seen & set(test)

    # La semilla: heldout_gain la pasa a split y a group_labels, y group_labels al KMeans
    trained.clear()
    seeds.clear()
    heldout_gain(df, ids, {}, seed=3)
    assert seeds == [3] * 5
    assert [set(train) for train, _ in split(ids, 3)] == trained
    clustered = []
    cluster = visit_groups.cluster_sessions
    monkeypatch.setattr(visit_groups, "cluster_sessions",
                        lambda matrix, seed=SEED, **kw: clustered.append(seed) or cluster(matrix, seed=seed, **kw))
    group_labels(df, ids, seed=7)
    assert clustered == [7]


def test_two_shared_kinds_pass_the_gate(tmp_path):
    """Positivo de la puerta: dos tipos que comparten estados. Una sola cadena los mezcla y los grupos predicen
    mejor: quedan 2 grupos, los lectores juntos y los creadores juntos."""
    groups, report = groups_of(tmp_path, two_kinds(shared=True))

    assert len(set(groups.values())) == 2
    assert len({groups[f"s{n}"] for n in range(0, 60, 2)}) == 1      # los lectores, juntos
    assert len({groups[f"s{n}"] for n in range(1, 60, 2)}) == 1      # los que crean, juntos
    assert len(report["heldout_gain"]) == FOLDS
    assert np.mean(report["heldout_gain"]) > 0
    assert "one_group" not in report
    assert report["sizes"] == [30, 30]

    # La ganancia del trozo 0, a mano (aquí la mezcla casi es el máximo: el test 7 lo distingue)
    df = parse_logs(write_log(tmp_path / "again.jsonl", two_kinds(shared=True)))
    assert report["heldout_gain"][0] == pytest.approx(hand_gain(df), abs=1e-12)


def test_one_random_chain_fails_the_gate(tmp_path):
    """Negativo de la puerta (el control de la consultora): una sola cadena al azar. El KMeans y las reglas 1 y 2
    dejan más de un grupo, pero no predicen mejor las visitas nuevas: queda uno."""
    groups, report = groups_of(tmp_path, one_random_chain())

    assert report["k"] > 1
    assert len(report["heldout_gain"]) == FOLDS        # la puerta ha actuado
    assert np.mean(report["heldout_gain"]) <= 0
    assert set(groups.values()) == {0}
    assert report["one_group"] == gate_text()
    assert describe(report) == f"1 ({gate_text()}); el plan es el de la cadena"

    # Las ganancias, a mano, de dos trozos: aquí los grupos se solapan y la mezcla (logaddexp) se separa del
    # máximo en ~0,4 por trozo, así que también se comprueba que es una mezcla
    df = parse_logs(write_log(tmp_path / "again.jsonl", one_random_chain()))
    for fold in (0, 4):
        assert report["heldout_gain"][fold] == pytest.approx(hand_gain(df, fold), abs=1e-9)


def test_kinds_with_nothing_in_common_need_no_groups(tmp_path):
    """Si dos tipos no comparten ninguna petición, una sola cadena ya los separa: los grupos no añaden nada
    (ganancia ~0 en la puerta) y no se ponen."""
    groups, report = groups_of(tmp_path, two_kinds(shared=False))

    assert len(report["heldout_gain"]) == FOLDS
    assert np.mean(report["heldout_gain"]) == pytest.approx(0, abs=1e-4)
    assert set(groups.values()) == {0}
    assert report["one_group"] == gate_text()


def test_too_few_sessions_is_one_group(tmp_path):
    """Con menos de 2 * FOLDS sesiones no se puede validar nada: un grupo, sin agrupar."""
    groups, report = groups_of(tmp_path, two_kinds()[:6])

    assert set(groups.values()) == {0}
    assert len(groups) == 6
    assert "demasiado pocas" in report["one_group"]
    assert report["one_group"] == "demasiado pocas sesiones (6) para validar grupos"
    assert report["sizes"] == [6]
    assert "heldout_gain" not in report

    # Con 2 * FOLDS = 10 sesiones ya se agrupa (5 lectores y 5 creadores: la regla 2 los junta)
    groups, report = groups_of(tmp_path, two_kinds()[:2 * FOLDS], "ten.jsonl")
    assert "k" in report
    assert not report["one_group"].startswith("demasiado pocas")
    assert set(groups.values()) == {0}


def test_gate_uses_the_plan_chain_arguments(tmp_path, monkeypatch):
    """Las cadenas de la puerta se hacen con los argumentos del plan (min_probability, endpoints, jar_weight)."""
    chain = {"min_probability": 0.05, "endpoints": [{"method": "GET", "endpoint": "/z"}], "jar_weight": 3}
    calls = []
    original = visit_groups.build_markov_model

    def recorder(df, **kwargs):
        calls.append(kwargs)
        return original(df, **kwargs)

    monkeypatch.setattr(visit_groups, "build_markov_model", recorder)
    _, report = find_visit_groups(parse_logs(write_log(tmp_path / "log.jsonl", two_kinds())), chain)

    assert "heldout_gain" in report
    assert len(calls) >= 2 * FOLDS                       # una cadena sola y al menos una por grupo, por trozo
    assert all(call == chain for call in calls)


def test_no_sessions_still_makes_no_groups(tmp_path, monkeypatch):
    """Con las reglas, un log sin sesiones sigue sin grupos (y sin agrupar ni pasar por la puerta), y en un log
    mixto las peticiones sin sessionId no entran ni en el agrupamiento ni en la puerta."""
    test_no_sessions_makes_no_groups(tmp_path)

    sessions = two_kinds()
    df = parse_logs(write_log(tmp_path / "none.jsonl", sessions, without_id=range(len(sessions))))

    def forbidden(*args, **kwargs):
        raise AssertionError("sin sesiones no se agrupa")

    with monkeypatch.context() as patch:
        for name in ("group_labels", "heldout_gain", "get_steps", "build_markov_model"):
            patch.setattr(visit_groups, name, forbidden)
        assert find_visit_groups(df) == ({}, {"sessions": 0, "one_group": "el log no tiene sesiones"})

    # Log mixto: cada sesión par de cada 5 sin sessionId; ni el KMeans ni las cadenas de la puerta las ven
    mixed = parse_logs(write_log(tmp_path / "mixed.jsonl", sessions, without_id=range(0, len(sessions), 5)))
    seen = []
    original = visit_groups.build_markov_model

    def recorder(df, **kwargs):
        seen.append(bool(df["session_id"].isna().any()))
        return original(df, **kwargs)

    monkeypatch.setattr(visit_groups, "build_markov_model", recorder)
    groups, report = find_visit_groups(mixed)
    assert set(groups) == set(mixed["session_id"].dropna())
    assert seen and not any(seen)


def test_merge_alike_follows_the_rules():
    """merge_alike directo: los valores aprobados, el umbral estricto, los empates, qué grupo se queda el
    número y el formato de cada fusión."""
    assert (SAME_NAVIGATION, MIN_GROUP, FOLDS, FLOOR, START) == (0.2, 10, 5, 1e-6, "<inicio>")

    def groups(*members):
        """members: una lista de secuencias por grupo (grupo = posición). Devuelve (labels, sequences)."""
        labels, sequences = {}, {}
        for group, seqs in enumerate(members):
            for n, sequence in enumerate(seqs):
                labels[f"g{group}-{n}"] = group
                sequences[f"g{group}-{n}"] = sequence
        return labels, sequences

    ab, ac = ["GET /a", "GET /b"], ["GET /a", "GET /c"]
    pq, pr = ["GET /p", "GET /q"], ["GET /p", "GET /r"]

    # Regla 1 con el umbral por defecto: una visita distinta de 10 (JS 0,186) se junta; dos (JS 0,268) no.
    # Mismo tamaño: se queda el número más bajo. La js va redondeada a 4 decimales.
    labels, sequences = groups([ab] * 10, [ab] * 9 + [ac])
    near = js_distance(navigation([ab] * 10), navigation([ab] * 9 + [ac]))
    assert 0.18 < near < SAME_NAVIGATION
    merged, merges = merge_alike(labels, sequences)
    assert merges == [{"groups": [0, 1], "js": round(near, 4), "why": "navegan igual"}]
    assert set(merged.values()) == {0}
    assert labels == groups([ab] * 10, [ab] * 9 + [ac])[0]          # no cambia el diccionario de entrada
    labels, sequences = groups([ab] * 10, [ab] * 8 + [ac] * 2)
    assert 0.26 < js_distance(navigation([ab] * 10), navigation([ab] * 8 + [ac] * 2)) < 0.4
    assert merge_alike(labels, sequences) == (labels, [])

    # El umbral es estricto (menor que): a distancia 1 justo (sin nada en común) con umbral 1, no se juntan
    labels, sequences = groups([ab] * 3, [pq] * 3)
    assert merge_alike(labels, sequences, threshold=1.0, min_size=0) == (labels, [])
    assert merge_alike(labels, sequences, threshold=1.0 + 1e-9, min_size=0)[1][0]["why"] == "navegan igual"

    # Empate de distancia en la regla 1: primero el par (i, j) más pequeño
    labels, sequences = groups([ab] * 10, [ab] * 9 + [ac], [pq] * 10, [pq] * 9 + [pr])
    _, merges = merge_alike(labels, sequences)
    assert [merge["groups"] for merge in merges] == [[0, 1], [2, 3]]

    # Regla 2: el más pequeño (empate de tamaño: el número más bajo, el 0 y no el 1) va con el más cercano
    # (el 3, a 0,46, y no el 2, a 0,82, ni el 1, a 1), y el grande se queda el número aunque sea más alto
    labels, sequences = groups([ab] * 2, [pq] * 2, [ac] * 12, [ab] * 6 + [ac] * 6)
    _, merges = merge_alike(labels, sequences)
    assert merges[0]["groups"] == [3, 0]
    assert merges[0]["why"] == "demasiado pequeño (2 sesiones)"
    assert merges[0]["js"] == round(js_distance(navigation([ab] * 2), navigation([ab] * 6 + [ac] * 6)), 4)
    # Un grupo con min_size sesiones justas ya no es demasiado pequeño
    assert merge_alike(labels, sequences, min_size=2) == (labels, [])
    # Con el mínimo por defecto (MIN_GROUP = 10): 9 sesiones son demasiado pocas, 10 ya no
    labels, sequences = groups([ab] * 9, [pq] * 20)
    assert merge_alike(labels, sequences)[1] == [{"groups": [1, 0], "js": 1.0, "why": "demasiado pequeño (9 sesiones)"}]
    labels, sequences = groups([ab] * 10, [pq] * 20)
    assert merge_alike(labels, sequences) == (labels, [])

    # Empate de distancia en la regla 2 (el contraexemplo del verificador: 1.0 y 0.9999999999999999 sin
    # redondear): el grupo pequeño, sin nada en común con el 1 ni con el 2, va con el 1
    tie = groups(
        [["GET /z2", "GET /z2", "GET /z1"], ["GET /z1"]],
        [["GET /a0", "GET /a2", "GET /a2", "GET /a0"], ["GET /a2", "GET /a2"], ["GET /a0"],
         ["GET /a1", "GET /a0", "GET /a2", "GET /a1"], ["GET /a0", "GET /a1"], ["GET /a1", "GET /a1"],
         ["GET /a1", "GET /a1", "GET /a0", "GET /a1"], ["GET /a1", "GET /a2", "GET /a1", "GET /a1", "GET /a0"],
         ["GET /a2", "GET /a1", "GET /a1", "GET /a2"], ["GET /a2", "GET /a1"],
         ["GET /a2", "GET /a0", "GET /a2", "GET /a0"], ["GET /a1", "GET /a0", "GET /a1", "GET /a2"]],
        [["GET /b1", "GET /b2", "GET /b2", "GET /b1", "GET /b0"], ["GET /b1", "GET /b2"],
         ["GET /b2", "GET /b1", "GET /b2", "GET /b2", "GET /b2"], ["GET /b1", "GET /b0", "GET /b1", "GET /b2", "GET /b1"],
         ["GET /b2", "GET /b2", "GET /b1", "GET /b2", "GET /b2"], ["GET /b1", "GET /b1", "GET /b0"], ["GET /b1"],
         ["GET /b0", "GET /b2", "GET /b1", "GET /b0"], ["GET /b1", "GET /b0", "GET /b1", "GET /b1", "GET /b0"],
         ["GET /b2", "GET /b2", "GET /b0"], ["GET /b2", "GET /b1", "GET /b1", "GET /b2", "GET /b1"], ["GET /b1", "GET /b2"]],
    )
    _, merges = merge_alike(*tie)
    assert merges[0] == {"groups": [1, 0], "js": 1.0, "why": "demasiado pequeño (2 sesiones)"}


def test_log_likelihood_counts_start_steps_and_end():
    """log P(sesión): el inicio, cada paso y el paso a END, siempre con + FLOOR (también lo que sí se ha visto)."""
    model = {"start": {"GET /a": 1.0},
             "transitions": {"GET /a": {"GET /b": 0.5, END: 0.5}, "GET /b": {END: 1.0}}}

    assert log_likelihood(["GET /a", "GET /b"], model) == pytest.approx(
        np.log(1 + FLOOR) + np.log(0.5 + FLOOR) + np.log(1 + FLOOR), abs=1e-12)
    assert log_likelihood(["GET /a"], model) == pytest.approx(np.log(1 + FLOOR) + np.log(0.5 + FLOOR), abs=1e-12)
    # Un estado que el modelo no tiene: ni inicio ni transiciones, sin fallar
    assert log_likelihood(["GET /z"], model) == pytest.approx(2 * np.log(FLOOR), abs=1e-9)
    assert log_likelihood(["GET /a", "GET /z"], model) == pytest.approx(
        np.log(1 + FLOOR) + np.log(FLOOR) + np.log(FLOOR), abs=1e-9)


def test_gate_decides_by_the_mean(tmp_path, monkeypatch):
    """La puerta juzga la media de los 5 trozos: > 0 deja los grupos; <= 0 (0 justo incluido), un solo grupo."""
    df = parse_logs(write_log(tmp_path / "log.jsonl", two_kinds()))
    for gains, kept in (([1.0, -0.1, -0.1, -0.1, -0.1], True),   # media > 0 aunque el mínimo y la mediana no
                        ([0.005] * 5, True),                      # poco, pero > 0
                        ([0.0] * 5, False),                       # 0 justo: no predice mejor
                        ([-1.0, 0.1, 0.1, 0.1, 0.1], False)):     # media < 0 aunque la mediana no
        monkeypatch.setattr(visit_groups, "heldout_gain", lambda *args, **kwargs: list(gains))
        groups, report = find_visit_groups(df)
        assert report["heldout_gain"] == gains
        if kept:
            assert len(set(groups.values())) == 2 and "one_group" not in report
        else:
            assert set(groups.values()) == {0} and report["one_group"] == gate_text()


# --- Un modelo por grupo (T-2.3) --------------------------------------------------------------------

PLAIN_CHAIN = {"min_probability": 0.0, "endpoints": None, "jar_weight": 1}   # los argumentos por defecto de main.py
FIVE_KEYS = {"weight", "start", "transitions", "status_transitions", "think_time_ms"}


def two_kinds_same_status(reading=30, writing=30, status=200):
    """`reading` lectores (GET /a -> GET /b) y `writing` que hacen GET /a -> POST /c -> GET /b -> POST /d, todos con
    el mismo código y alternados como two_kinds() (los que sobran, al final). Con 30 y 30, después de GET /a con 200
    la cadena general da GET /b 0,5 y POST /c 0,5: el código no separa los dos tipos."""
    readers_ = [visit(["GET /a", "GET /b"], 2 + n % 3, status=status) for n in range(reading)]
    writers_ = [visit(["GET /a", "POST /c", "GET /b", "POST /d"], 3 + n % 4, status=status) for n in range(writing)]
    both = min(reading, writing)
    rest = readers_[both:] + writers_[both:]
    return [s for pair in zip(readers_, writers_) for s in pair] + rest


def same_status_df(tmp_path, name="same.jsonl", without_id=(), **kinds):
    return parse_logs(write_log(tmp_path / name, two_kinds_same_status(**kinds), without_id=without_id))


def by_hand(df, reading=15):
    """Los grupos hechos a mano: los `reading` lectores (s0, s2, ...) en el grupo 1 y los demás en el 0."""
    readers_ = {f"s{n}" for n in range(0, 2 * reading, 2)}
    return {session: int(session in readers_) for session in df["session_id"].dropna().unique()}


def test_status_cases_count_like_the_chain(tmp_path):
    """Los casos de cada pareja (estado, código) se cuentan como en build_status_transitions: mismas claves."""
    df = same_status_df(tmp_path)
    cases = status_cases(df)
    assert cases["GET /a"]["200"] == 60
    assert cases["POST /c"]["200"] == 30
    chain = build_status_transitions(df)
    assert set(cases) == set(chain)
    assert all(set(cases[state]) == set(chain[state]) for state in chain)

    # Varios códigos, filas sin status (no cuentan) y una sesión sin sessionId (no cuenta)
    sessions = [[("GET", "/a", 200, 0), ("GET", "/a", 404, 1), ("POST", "/b", None, 2)]] * 4
    df = parse_logs(write_log(tmp_path / "mixed.jsonl", sessions, without_id=[3]))
    assert status_cases(df) == {"GET /a": {"200": 3, "404": 3}}
    chain = build_status_transitions(df)
    assert set(chain) == {"GET /a"} and set(chain["GET /a"]) == {"200", "404"}

    # Sin sesiones, sin status o sin log: nada
    assert status_cases(None) == {}
    no_ids = two_kinds_same_status(4, 4)
    assert status_cases(parse_logs(write_log(tmp_path / "no_ids.jsonl", no_ids, without_id=range(8)))) == {}
    assert status_cases(same_status_df(tmp_path, "no_status.jsonl", reading=4, writing=4, status=None)) == {}
    assert status_cases(df.drop(columns="status")) == {}


def test_keep_frequent_statuses_boundary():
    """19 casos no bastan y 20 sí; un estado sin ningún código no sale; el diccionario recibido no cambia."""
    assert MIN_STATUS_CASES == 20
    transitions = {"GET /a": {"200": {"GET /b": 0.7, END: 0.3}, "404": {END: 1.0}},
                   "GET /b": {"500": {END: 1.0}},
                   "GET /c": {"200": {END: 1.0}}}
    cases = {"GET /a": {"200": 20, "404": 19}, "GET /b": {"500": 3}}     # GET /c no tiene casos: 0
    before = copy.deepcopy(transitions)

    kept = keep_frequent_statuses(transitions, cases)
    assert kept == {"GET /a": {"200": {"GET /b": 0.7, END: 0.3}}}
    assert transitions == before
    kept["GET /a"]["200"]["GET /b"] = 0          # el nuevo no comparte nada con el que recibe
    assert transitions == before

    every = keep_frequent_statuses(transitions, cases, min_cases=19)
    assert every == {"GET /a": {"200": {"GET /b": 0.7, END: 0.3}, "404": {END: 1.0}}}
    every["GET /a"]["999"] = {}                  # tampoco comparte el diccionario del estado (aquí se quedan todos)
    every["GET /a"]["404"][END] = 0
    every["otro"] = {}
    assert transitions == before
    assert keep_frequent_statuses(transitions, {}) == {}
    assert keep_frequent_statuses({}, cases) == {}


def test_group_status_transitions_are_the_groups_own(tmp_path):
    """El problema del 16-17: cada grupo lleva sus transiciones por código, no las generales."""
    df = same_status_df(tmp_path)
    groups, report = find_visit_groups(df, PLAIN_CHAIN)
    assert report["sizes"] == [30, 30], report
    assert {s for s, g in groups.items() if g == groups["s0"]} == {f"s{n}" for n in range(0, 60, 2)}

    model = build_markov_model(df)
    parts = build_group_models(df, groups, model, PLAIN_CHAIN, DEFAULT_PAUSE_MS)
    reading, writing = parts[groups["s0"]], parts[groups["s1"]]
    assert reading["status_transitions"]["GET /a"]["200"] == {"GET /b": 1.0}
    assert writing["status_transitions"]["GET /a"]["200"] == {"POST /c": 1.0}
    assert model["status_transitions"]["GET /a"]["200"] == {"GET /b": 0.5, "POST /c": 0.5}


def test_small_group_falls_back_to_its_general(tmp_path):
    """Un grupo de 15 lectores no llega a 20 casos: sin transiciones por código, usa sus transiciones generales,
    que son las suyas (después de GET /a, solo GET /b). Con 20 lectores, ya llevan las suyas."""
    df = same_status_df(tmp_path, reading=15)
    model = build_markov_model(df)
    parts = build_group_models(df, by_hand(df), model, PLAIN_CHAIN, DEFAULT_PAUSE_MS)
    assert parts[1]["status_transitions"] == {}
    assert parts[1]["start"] == {"GET /a": 1.0}
    assert parts[1]["transitions"] == {"GET /a": {"GET /b": 1.0}, "GET /b": {END: 1.0}}
    assert set(model["transitions"]["GET /a"]) == {"GET /b", "POST /c"}       # la general de todos, no la suya
    assert parts[0]["status_transitions"]["GET /a"]["200"] == {"POST /c": 1.0}  # 30 casos: se queda

    df = same_status_df(tmp_path, "twenty.jsonl", reading=20)
    parts = build_group_models(df, by_hand(df, 20), build_markov_model(df), PLAIN_CHAIN, DEFAULT_PAUSE_MS)
    assert parts[1]["status_transitions"]["GET /a"] == {"200": {"GET /b": 1.0}}

    # El inicio también es el del grupo: si los lectores empiezan por GET /e, el suyo es solo GET /e
    sessions = [[("GET", "/e", 200, 0), ("GET", "/b", 200, 2)] if n % 2 == 0 and n < 30 else s
                for n, s in enumerate(two_kinds_same_status(reading=15))]
    df = parse_logs(write_log(tmp_path / "starts.jsonl", sessions))
    model = build_markov_model(df)
    parts = build_group_models(df, by_hand(df), model, PLAIN_CHAIN, DEFAULT_PAUSE_MS)
    assert parts[1]["start"] == {"GET /e": 1.0}
    assert parts[0]["start"] == {"GET /a": 1.0}
    assert model["start"] == pytest.approx({"GET /a": 30 / 45, "GET /e": 15 / 45})

    # Los casos se cuentan sobre las peticiones, antes de la poda: 20 lectores en los que uno se va después de
    # GET /a (END 0,05, que --min-probability 0.1 quita) siguen teniendo 20 casos de GET /a con 200
    sessions = two_kinds_same_status(reading=20)
    sessions[0] = visit(["GET /a"], 2)
    df = parse_logs(write_log(tmp_path / "pruned.jsonl", sessions))
    chain = {**PLAIN_CHAIN, "min_probability": 0.1}
    model = build_markov_model(df, 0.1)
    parts = build_group_models(df, by_hand(df, 20), model, chain, DEFAULT_PAUSE_MS)
    assert status_cases(df[df["session_id"].isin({f"s{n}" for n in range(0, 40, 2)})])["GET /a"] == {"200": 20}
    assert parts[1]["status_transitions"]["GET /a"] == {"200": {"GET /b": 1.0}}


@pytest.mark.parametrize("min_probability, endpoints, jar_weight, max_steps, pause", [
    (0.0, None, 1, 50, DEFAULT_PAUSE_MS),
    (0.05, [{"method": "GET", "endpoint": "/a"}, {"method": "GET", "endpoint": "/z"}], 3, 7, [0]),
    (0.0, [{"method": "GET", "endpoint": "/a"}, {"method": "GET", "endpoint": "/z"}], 3, 7, [0]),
], ids=["defecto", "jar", "jar-sin-poda"])
def test_group_models_are_the_chain_on_group_sessions(tmp_path, min_probability, endpoints, jar_weight, max_steps,
                                                       pause):
    """Cada grupo es la cadena de main.py (build_markov_model + build_think_times + add_default_pauses) con los
    argumentos del plan, sobre las sesiones del grupo."""
    df = same_status_df(tmp_path)
    chain = {"min_probability": min_probability, "endpoints": endpoints, "jar_weight": jar_weight}
    groups, _ = find_visit_groups(df, chain)
    model = build_markov_model(df, min_probability, max_steps, endpoints=endpoints, jar_weight=jar_weight)
    parts = build_group_models(df, groups, model, chain, pause)
    assert len(parts) == len(set(groups.values())) == 2

    for number, part in enumerate(parts):
        df_group = df[df["session_id"].isin({s for s, g in groups.items() if g == number})]
        expected = build_markov_model(df_group, min_probability, max_steps, endpoints=endpoints, jar_weight=jar_weight)
        assert part["start"] == expected["start"]
        assert part["transitions"] == expected["transitions"]
        assert part["think_time_ms"] == add_default_pauses(build_think_times(df_group), expected, pause)
        assert part["status_transitions"] == keep_frequent_statuses(expected["status_transitions"],
                                                                    status_cases(df_group))
        if endpoints:
            # El .jar llega a cada grupo, y GET /z (que nadie usa) lleva la pausa por defecto
            assert part["transitions"]["GET /z"] == pytest.approx({"GET /a": 1 / 3, "GET /z": 1 / 3, END: 1 / 3})
            assert part["think_time_ms"]["GET /z"] == {"GET /a": [0], "GET /z": [0]}
            assert part["transitions"]["GET /a"] != parts[1 - number]["transitions"]["GET /a"]
            if min_probability == 0:
                # Sin poda se ve el peso del .jar: 3 casos inventados a partes iguales entre GET /a, GET /z y END,
                # más los 30 del grupo después de GET /a
                assert part["transitions"]["GET /a"]["GET /z"] == pytest.approx(1 / 33)


def test_every_group_has_the_five_keys(tmp_path):
    """Las cinco claves siempre, también con status_transitions vacío (si faltara, el grupo heredaría las
    generales en el T-2.4)."""
    for name, status in (("with.jsonl", 200), ("without.jsonl", None)):
        df = same_status_df(tmp_path, name, reading=15, status=status)
        parts = build_group_models(df, by_hand(df), build_markov_model(df), PLAIN_CHAIN, DEFAULT_PAUSE_MS)
        assert len(parts) == 2
        for part in parts:
            assert set(part) == FIVE_KEYS
        assert parts[1]["status_transitions"] == {}
        if status is None:
            assert parts[0]["status_transitions"] == {}


def test_weights_sum_to_one_and_match_sizes(tmp_path):
    """Cada peso es la parte de las sesiones agrupadas que tiene su grupo; las filas sin sesión no cuentan."""
    df = same_status_df(tmp_path, reading=15)
    parts = build_group_models(df, by_hand(df), build_markov_model(df), PLAIN_CHAIN, DEFAULT_PAUSE_MS)
    assert [part["weight"] for part in parts] == pytest.approx([30 / 45, 15 / 45])
    assert sum(part["weight"] for part in parts) == pytest.approx(1)

    # Log mixto: la última sesión (un creador) va sin sessionId y no entra en ningún grupo ni en los pesos
    df = same_status_df(tmp_path, "mixed.jsonl", reading=15, without_id=[44])
    groups = by_hand(df)
    assert len(groups) == 44
    parts = build_group_models(df, groups, build_markov_model(df), PLAIN_CHAIN, DEFAULT_PAUSE_MS)
    assert [part["weight"] for part in parts] == pytest.approx([29 / 44, 15 / 44])
    assert sum(part["weight"] for part in parts) == pytest.approx(1)
    for number, part in enumerate(parts):
        alone = build_markov_model(df[df["session_id"].isin({s for s, g in groups.items() if g == number})])
        assert part["start"] == alone["start"] == {"GET /a": 1.0}
        assert part["transitions"] == alone["transitions"]

    df = same_status_df(tmp_path, "even.jsonl")
    groups, report = find_visit_groups(df, PLAIN_CHAIN)
    parts = build_group_models(df, groups, build_markov_model(df), PLAIN_CHAIN, DEFAULT_PAUSE_MS)
    assert [part["weight"] for part in parts] == [size / sum(report["sizes"]) for size in report["sizes"]]


def test_group_states_must_fit_the_global_model(tmp_path, monkeypatch):
    """Un grupo con un estado que el modelo general no tiene es un error (el Switch del plan es uno solo)."""
    df = same_status_df(tmp_path, reading=15)
    groups = by_hand(df)
    model = build_markov_model(df)
    build_group_models(df, groups, model, PLAIN_CHAIN, DEFAULT_PAUSE_MS)      # sin error
    for number in (0, 1):
        df_group = df[df["session_id"].isin({s for s, g in groups.items() if g == number})]
        assert set(build_markov_model(df_group)["states"]) <= set(model["states"])

    original = visit_groups.build_markov_model

    def with_a_new_state(*args, **kwargs):
        result = original(*args, **kwargs)
        result["states"] = sorted([*result["states"], "GET /nou"])
        return result

    monkeypatch.setattr(visit_groups, "build_markov_model", with_a_new_state)
    with pytest.raises(ValueError) as error:
        build_group_models(df, groups, model, PLAIN_CHAIN, DEFAULT_PAUSE_MS)
    assert str(error.value) == ("un grupo tiene estados que no están en el modelo general: "
                                "el Switch del plan no los encontraría")


def test_main_prints_the_group_models(tmp_path, monkeypatch):
    """main.py con --visit-groups escribe la línea de los modelos debajo de la de los grupos, y les pasa los
    argumentos del plan; con dos grupos, el .jmx lleva el selector de grupo (T-2.4)."""
    log = str(write_log(tmp_path / "log.jsonl", two_kinds_same_status()))
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    result = subprocess.run([sys.executable, "main.py", "--logs", log, "--visit-groups",
                             "--output", str(tmp_path / "grouped.jmx")],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    first = lines.index("Grupos de visita: 2 (30, 30 sesiones)")
    assert lines[first + 1] == "  2 modelos de grupo; estados con distribución propia por código (al menos 20 casos): 2, 4"
    assert sum("modelos de grupo" in line for line in lines) == 1
    two_codes = {"GET /a": {"200": {END: 1.0}, "404": {END: 1.0}}, "GET /b": {"200": {END: 1.0}}}
    assert describe_models([{"status_transitions": two_codes}, {"status_transitions": {}}]) == \
        "2 modelos de grupo; estados con distribución propia por código (al menos 20 casos): 2, 0"
    assert sha256(generate(["--logs", log], tmp_path / "plain.jmx")) != sha256(tmp_path / "grouped.jmx")
    assert (tmp_path / "grouped.jmx").read_text(encoding="utf-8").count('testname="Elegir grupo de visita"') == 1

    # Los argumentos que main.py da a build_group_models (en el mismo proceso, con un espía)
    import runpy
    seen = []
    real = visit_groups.build_group_models

    def spy(df, groups, model, chain, default_pause_ms):
        seen.append((len(df), groups, model["max_steps"], chain, default_pause_ms))
        return real(df, groups, model, chain, default_pause_ms)

    monkeypatch.setattr(visit_groups, "build_group_models", spy)
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(sys, "argv", ["main.py", "--logs", log, "--visit-groups", "--jar", JAR,
                                      "--min-probability", "0.05", "--jar-weight", "3", "--max-steps", "7",
                                      "--default-pause", "0-2", "--output", str(tmp_path / "spy.jmx")])
    runpy.run_path("main.py", run_name="__main__")
    assert len(seen) == 1
    rows, groups, max_steps, chain, pause = seen[0]
    assert rows == len(parse_logs(log))
    assert set(groups) == {f"s{n}" for n in range(60)}
    assert max_steps == 7
    assert chain["min_probability"] == 0.05 and chain["jar_weight"] == 3
    assert {(e["method"], e["endpoint"]) for e in chain["endpoints"]}      # los del .jar
    assert pause == [0, 500, 1000, 1500, 2000]


# --- El selector de grupo del .jmx (T-2.4) ----------------------------------------------------------

PICKER = "Elegir grupo de visita"
FIRST = "Elegir primera petición"
NEXT = "Elegir siguiente petición (Markov)"
REFERENCE = "bench/data/bankapp_vall_pic_3h.jsonl"
HARNESS = ROOT / "tests" / "visit_groups_walk.groovy"
JMETER = jmeter_binary()
needs_jmeter = pytest.mark.skipif(not JMETER.exists(), reason=f"no hay JMeter en {JMETER} (ni en $JMETER_BIN)")
# Los argumentos de main.py por defecto (--min-probability, --max-steps, --jar-weight y --default-pause)
MAIN_DEFAULTS = {"min_probability": 0.0, "max_steps": 50, "jar_weight": 1, "default_pause": "1-3"}
LITERAL = re.compile(r"'''((?:\\.|[^\\'])*)'''")
JOIN = "].join()"


def jsr223_scripts(plan):
    """El script de cada JSR223 del plan, por su testname."""
    root = ET.parse(plan).getroot()
    return {element.get("testname"): element.findtext("stringProp[@name='script']")
            for element in root.iter() if element.tag.startswith("JSR223")}


def unescape(literal):
    """Lo que vale un literal '''...''' de Groovy escapado como en el generador (\\\\ y \\')."""
    return re.sub(r"\\(.)", r"\1", literal, flags=re.S)


def groovy_value(expression):
    """El texto que vale una expresión ['''...''', '''...'''].join(): comprueba que no hay nada más."""
    assert expression.startswith("[") and expression.endswith(JOIN), expression[:80]
    inner = expression[1:-len(JOIN)]
    chunks = LITERAL.findall(inner)
    assert ", ".join(f"'''{chunk}'''" for chunk in chunks) == inner
    return chunks, "".join(unescape(chunk) for chunk in chunks)


def embedded_literal(script):
    """El literal del modelo general que markov_common.groovy incrusta al principio de cada script."""
    start = script.index("parseText('''") + len("parseText('''")
    return script[start:script.index("''')\n    vars.putObject(\"stormModel\", model)")]


def embedded_model(script):
    return json.loads(unescape(embedded_literal(script)))


def picker_expression(script):
    start = script.index("def data = new JsonSlurper().parseText(") + len("def data = new JsonSlurper().parseText(")
    return script[start:script.index(")\n    def models = data.groups.collect")]


def picker_groups(script):
    """El JSON de los grupos del selector: {"weights": [...], "groups": [...]}."""
    return json.loads(groovy_value(picker_expression(script))[1])


def close(a, b, path="$"):
    """a y b iguales, con los números a 1e-12."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and set(a) == set(b), path
        for key in a:
            close(a[key], b[key], f"{path}.{key}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), path
        for n, (x, y) in enumerate(zip(a, b)):
            close(x, y, f"{path}[{n}]")
    elif isinstance(a, (int, float)) and not isinstance(a, bool):
        assert isinstance(b, (int, float)) and abs(a - b) <= 1e-12, (path, a, b)
    else:
        assert a == b, (path, a, b)


def same_status_log(tmp_path, name="same.jsonl", **kinds):
    return str(write_log(tmp_path / name, two_kinds_same_status(**kinds)))


def plans(tmp_path, inputs, name="plan"):
    """El plan sin --visit-groups y con."""
    plain = generate(inputs, tmp_path / f"{name}_plain.jmx")
    grouped = generate([*inputs, "--visit-groups"], tmp_path / f"{name}_grouped.jmx")
    return plain, grouped


def new_session_tree(root):
    """El hashTree de «Nueva sesión»: el que va justo después del TestAction."""
    for parent in root.iter():
        children = list(parent)
        for n, child in enumerate(children):
            if child.get("testname") == "Nueva sesión":
                assert children[n + 1].tag == "hashTree"
                return children[n + 1]
    raise AssertionError("el plan no tiene «Nueva sesión»")


def walk(plan, folder, sessions, code="200"):
    """Hace `sessions` visitas con el banco Groovy y los scripts del plan; devuelve walks.jsonl."""
    scripts = jsr223_scripts(plan)
    folder.mkdir()
    for name, testname in (("pick", PICKER), ("start", FIRST), ("next", NEXT)):
        (folder / f"{name}.groovy").write_text(scripts[testname], encoding="utf-8")
    lib = JMETER.parent.parent / "lib"
    result = subprocess.run(["java", "-cp", f"{lib}/*:{lib}/ext/ApacheJMeter_core.jar", "groovy.ui.GroovyMain",
                             str(HARNESS), str(folder), str(sessions), code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    walks = [json.loads(line) for line in (folder / "walks.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(walks) == sessions
    return walks


def check_walks(walks, general, data, code="200", shares=True):
    """Cada visita sigue el modelo de su grupo: la parte de visitas es el peso, empieza por un inicio del grupo
    sin pausa, cada paso es posible en el grupo (por código si lo hay), la pausa es una del grupo y el índice el
    del modelo general."""
    weights, parts = data["weights"], data["groups"]
    counts = Counter(w["group"] for w in walks)
    assert set(counts) <= set(range(len(parts)))
    for group, weight in enumerate(weights if shares else []):
        assert abs(counts[group] / len(walks) - weight) <= 0.03, (group, counts[group], weight)
    for w in walks:
        part, steps = parts[w["group"]], w["steps"]
        if not steps:
            assert w["skipped"]
            continue
        assert part["start"].get(steps[0][0], 0) > 0
        assert steps[0][1] == 0
        for state, _, index in steps:
            assert index == general["states"].index(state)
        distributions = []
        for state, _, _ in steps:
            distributions.append(part["status_transitions"].get(state, {}).get(code)
                                 or part["transitions"].get(state) or {END: 1})
        for (state, _, _), (following, pause, _), distribution in zip(steps, steps[1:], distributions):
            assert distribution.get(following, 0) > 0, (w["group"], state, following)
            pauses = part["think_time_ms"].get(state, {}).get(following)
            assert (pause in pauses) if pauses else pause == 0, (state, following, pause)
        # Cómo acaba: el grupo permite END, se llega a max_steps o se omite una petición sin id
        assert w["skipped"] or len(steps) >= general["max_steps"] or distributions[-1].get(END, 0) > 0
    return counts


def small_inputs():
    """Un modelo pequeño hecho a mano para llamar a generate_jmx directamente."""
    model = {"states": ["GET /a", "GET /b"], "start": {"GET /a": 1.0},
             "transitions": {"GET /a": {"GET /b": 1.0}, "GET /b": {END: 1.0}}, "status_transitions": {},
             "max_steps": 10}
    think_times = {"GET /a": {"GET /b": [1000, 2000]}}
    profile = {"vusers": 2, "ramp_up_seconds": 1, "duration_seconds": 10}
    return model, think_times, profile


def test_plan_without_groups_is_the_chain_plan(tmp_path):
    """Negativo: con un solo grupo (o ninguno), --visit-groups no cambia ni un byte del plan."""
    log_paces = str(write_log(tmp_path / "paces.jsonl", one_kind_two_paces()))
    log_random = str(write_log(tmp_path / "random.jsonl", one_random_chain()))
    sessions = two_kinds_same_status()
    log_no_id = str(write_log(tmp_path / "no_id.jsonl", sessions, without_id=range(len(sessions))))
    for n, inputs in enumerate((["--logs", log_paces], ["--logs", log_random], ["--logs", log_no_id],
                                ["--jar", JAR])):
        plain, grouped = plans(tmp_path, inputs, name=f"p{n}")
        assert sha256(plain) == sha256(grouped), inputs
        assert PICKER not in grouped.read_text(encoding="utf-8")


def test_plan_adds_only_the_group_picker(tmp_path):
    """Con dos grupos, el plan es el de la cadena más un solo elemento, antes de «Elegir primera petición»."""
    plain, grouped = plans(tmp_path, ["--logs", same_status_log(tmp_path)])
    root = ET.parse(grouped).getroot()
    pickers = [e for e in root.iter("JSR223PreProcessor") if e.get("testname") == PICKER]
    assert len(pickers) == 1
    assert sum(e.get("testname") == PICKER for e in root.iter()) == 1

    tree = new_session_tree(root)
    children = list(tree)
    assert [c.get("testname") for c in children if c.tag != "hashTree"] == [PICKER, FIRST]
    assert children[0].get("testname") == PICKER and children[1].tag == "hashTree" and len(children[1]) == 0
    # El selector se declara como «Elegir primera petición» (groovy, caché...): si no, JMeter lo rechaza en cada
    # visita sin parar la prueba y la visita sigue con el modelo general
    first = children[2]
    assert first.get("testname") == FIRST
    for element in (children[0], first):
        assert element.get("guiclass") == "TestBeanGUI" and element.get("testclass") == "JSR223PreProcessor"
    props = lambda element: [(e.get("name"), e.text) for e in element.findall("stringProp") if e.get("name") != "script"]
    assert props(children[0]) == props(first)
    assert dict(props(children[0])) == {"scriptLanguage": "groovy", "parameters": None, "filename": None,
                                        "cacheKey": "true"}
    tree.remove(children[0])
    tree.remove(children[1])
    assert ET.canonicalize(ET.tostring(root, encoding="unicode"), strip_text=True) == \
        ET.canonicalize(from_file=str(plain), strip_text=True)


def test_picker_carries_the_group_models(tmp_path):
    """El JSON del selector son los pesos y los modelos de build_group_models con los argumentos de main.py, y
    el modelo general incrustado es el mismo que el de «Elegir primera petición»."""
    chain = {"min_probability": MAIN_DEFAULTS["min_probability"], "endpoints": None,
             "jar_weight": MAIN_DEFAULTS["jar_weight"]}
    # Con 40 lectores y 20 creadores los pesos son distintos (2/3 y 1/3), escritos a mano
    for name, kinds, weights in (("same", {}, [0.5, 0.5]), ("uneven", {"reading": 40, "writing": 20}, [2 / 3, 1 / 3])):
        log = same_status_log(tmp_path, name=f"{name}.jsonl", **kinds)
        grouped = generate(["--logs", log, "--visit-groups"], tmp_path / f"{name}.jmx")
        scripts = jsr223_scripts(grouped)

        df = parse_logs(log)
        model = build_markov_model(df, chain["min_probability"], MAIN_DEFAULTS["max_steps"],
                                   endpoints=None, jar_weight=chain["jar_weight"])
        groups, _ = find_visit_groups(df, chain)
        parts = build_group_models(df, groups, model, chain, pause_range(MAIN_DEFAULTS["default_pause"]))
        expected = {"weights": [p["weight"] for p in parts],
                    "groups": [{key: p[key] for key in GROUP_KEYS} for p in parts]}
        assert len(parts) == 2
        data = picker_groups(scripts[PICKER])
        close(data, json.loads(json.dumps(expected)))
        close(data["weights"], weights)

    # El modelo general: el mismo literal en el selector y en «Elegir primera petición», y es el de main.py
    assert embedded_literal(scripts[PICKER]) == embedded_literal(scripts[FIRST])
    general = embedded_model(scripts[FIRST])
    close(general["start"], model["start"])
    close(general["transitions"], model["transitions"])
    assert general["states"] == model["states"]

    # El resto del selector es la plantilla, con la expresión en lugar del marcador
    template = (TEMPLATES_DIR / "visit_group.groovy").read_text(encoding="utf-8")
    assert scripts[PICKER].endswith(template.replace("__GROUPS_JSON__", picker_expression(scripts[PICKER])))
    common = (TEMPLATES_DIR / "markov_common.groovy").read_text(encoding="utf-8")
    assert scripts[PICKER].startswith(common.split("__MODEL_JSON__")[0])


def test_picker_groups_have_their_own_status_transitions(tmp_path):
    """Regresión del 16-17: cada grupo lleva sus status_transitions; si no, putAll dejaría las generales, que
    next_request.groovy consulta primero, y los lectores harían GET /a -> POST /c."""
    grouped = generate(["--logs", same_status_log(tmp_path), "--visit-groups"], tmp_path / "grouped.jmx")
    scripts = jsr223_scripts(grouped)
    data = picker_groups(scripts[PICKER])
    assert len(data["groups"]) == 2
    for part in data["groups"]:
        assert set(part) == set(GROUP_KEYS)
    readers_ = [part for part in data["groups"]
                if part["status_transitions"].get("GET /a", {}).get("200") == {"GET /b": 1.0}]
    assert len(readers_) == 1
    general = embedded_model(scripts[FIRST])
    close(general["status_transitions"]["GET /a"]["200"], {"GET /b": 0.5, "POST /c": 0.5})


def test_groovy_text_survives_quotes_backslashes_and_size():
    """Límite: comillas triples, barras, comillas dobles, é, un emoji y $, en 4 trozos."""
    piece = "a'''b\\c\"d é 😀 $x ${y} \\' '"
    text = (piece * (3 * CHUNK // len(piece) + 2))[:3 * CHUNK + 7]
    assert len(text) == 3 * CHUNK + 7
    chunks, value = groovy_value(_groovy_text(text))
    assert len(chunks) == 4
    assert value == text
    # Vacío: un solo trozo vacío
    assert _groovy_text("") == "[''''''].join()"
    assert groovy_value(_groovy_text(""))[1] == ""
    # Cada trozo empieza y acaba en un trozo de CHUNK caracteres del texto
    assert [unescape(chunk) for chunk in chunks] == [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)]


def test_generate_jmx_without_groups_is_unchanged(tmp_path):
    """Negativo: visit_groups ausente, None o [] escriben el mismo fichero, byte a byte."""
    model, think_times, profile = small_inputs()
    paths = [tmp_path / f"{name}.jmx" for name in ("absent", "none", "empty")]
    generate_jmx(copy.deepcopy(model), think_times, profile, str(paths[0]))
    generate_jmx(copy.deepcopy(model), think_times, profile, str(paths[1]), visit_groups=None)
    generate_jmx(copy.deepcopy(model), think_times, profile, str(paths[2]), visit_groups=[])
    assert paths[0].read_bytes() == paths[1].read_bytes() == paths[2].read_bytes()
    assert PICKER not in paths[0].read_text(encoding="utf-8")


def test_plan_keeps_one_thread_group_and_vusers(tmp_path):
    """Negativo: un solo Thread Group y el mismo -Jvusers con grupos y sin."""
    plain, grouped = plans(tmp_path, ["--logs", same_status_log(tmp_path)])
    threads = []
    for plan in (plain, grouped):
        root = ET.parse(plan).getroot()
        groups = list(root.iter("ThreadGroup"))
        assert len(groups) == 1
        threads.append(groups[0].findtext("stringProp[@name='ThreadGroup.num_threads']"))
    assert threads[0] == threads[1]
    assert threads[1].startswith("${__P(vusers,")


def test_templates_still_read_the_model_from_the_thread():
    """Contrato con las plantillas que no se tocan: leen el modelo de stormModel antes que el incrustado."""
    common = (TEMPLATES_DIR / "markov_common.groovy").read_text(encoding="utf-8")
    start = (TEMPLATES_DIR / "session_start.groovy").read_text(encoding="utf-8")
    following = (TEMPLATES_DIR / "next_request.groovy").read_text(encoding="utf-8")
    assert 'def model = vars.getObject("stormModel")\nif (model == null) {' in common
    assert "goTo(pick(model.start))" in start
    assert following.index("model.status_transitions") < following.index("model.transitions[current]")
    assert "model.think_time_ms[current]" in following
    assert following.count("Thread.sleep(pauseMs)") == 1


@needs_jmeter
def test_groovy_sessions_follow_their_group(tmp_path):
    """Groovy de verdad: cada visita usa el inicio, las transiciones (por código) y las pausas de su grupo, y
    ninguna visita de los lectores hace GET /a -> POST /c."""
    grouped = generate(["--logs", same_status_log(tmp_path), "--visit-groups"], tmp_path / "grouped.jmx")
    scripts = jsr223_scripts(grouped)
    data = picker_groups(scripts[PICKER])
    general = embedded_model(scripts[FIRST])
    walks = walk(grouped, tmp_path / "walk", 4000)
    counts = check_walks(walks, general, data)
    assert set(counts) == {0, 1}

    readers_group = next(n for n, part in enumerate(data["groups"])
                         if part["status_transitions"].get("GET /a", {}).get("200") == {"GET /b": 1.0})
    reader_walks = [w for w in walks if w["group"] == readers_group]
    assert reader_walks
    for w in reader_walks:
        states = [state for state, _, _ in w["steps"]]
        assert ("GET /a", "POST /c") not in set(zip(states, states[1:])), states
    # Los otros sí lo hacen (el control: el banco ve la diferencia)
    other = [w for w in walks if w["group"] != readers_group]
    assert any(("GET /a", "POST /c") in set(zip(s, s[1:])) for s in ([x for x, _, _ in w["steps"]] for w in other))

    # Con un código que no tiene distribución propia (404), mandan las transitions del grupo (no las generales)
    assert all("404" not in statuses for part in data["groups"] for statuses in part["status_transitions"].values())
    walks_404 = walk(grouped, tmp_path / "walk404", 2000, code="404")
    check_walks(walks_404, general, data, code="404", shares=False)
    for w in walks_404:
        if w["group"] == readers_group:
            states = [state for state, _, _ in w["steps"]]
            assert ("GET /a", "POST /c") not in set(zip(states, states[1:])), states


@needs_jmeter
def test_groovy_sessions_on_the_reference_log(tmp_path):
    """Lo mismo con el log de referencia (--session --session-users 1,2,3) y 2.000 visitas."""
    plain, grouped = plans(tmp_path, ["--logs", REFERENCE, "--session", "--session-users", "1,2,3"])
    scripts = jsr223_scripts(grouped)
    if PICKER not in scripts:
        assert sha256(plain) == sha256(grouped), "un solo grupo en el log de referencia: el plan es el de la cadena"
        return
    data = picker_groups(scripts[PICKER])
    general = embedded_model(scripts[FIRST])
    assert len(data["groups"]) > 1
    counts = check_walks(walk(grouped, tmp_path / "walk", 2000), general, data)
    assert set(counts) == set(range(len(data["groups"])))


@needs_jmeter
def test_groovy_compiles_a_groups_json_over_64k(tmp_path):
    """Límite: un JSON de grupos de más de 70.000 caracteres va a trozos, compila y hace 200 visitas, con las
    pausas del grupo (3-4 s), no las del modelo general (1-2 s)."""
    model, think_times, profile = small_inputs()
    count = 600
    group = {"weight": 1 / count, "start": {"GET /a": 1.0},
             "transitions": {"GET /a": {"GET /b": 1.0}, "GET /b": {END: 1.0}},
             "status_transitions": {}, "think_time_ms": {"GET /a": {"GET /b": [3000, 4000]}}}
    plan = tmp_path / "big.jmx"
    generate_jmx(model, think_times, profile, str(plan), visit_groups=[copy.deepcopy(group) for _ in range(count)])
    scripts = jsr223_scripts(plan)
    chunks, value = groovy_value(picker_expression(scripts[PICKER]))
    assert len(value) > 70_000
    assert len(chunks) == math.ceil(len(value) / CHUNK) > 7
    walks = walk(plan, tmp_path / "walk", 200)
    for w in walks:
        assert not w["skipped"]
        assert [(state, index) for state, _, index in w["steps"]] == [("GET /a", 0), ("GET /b", 1)]
        assert w["steps"][0][1] == 0 and w["steps"][1][1] in (3000, 4000)
    assert len({w["group"] for w in walks}) > 50


def test_picker_json_is_ascii_and_needs_its_keys(tmp_path):
    """El JSON de los grupos va en ASCII puro; un grupo sin status_transitions hace petar el generador (KeyError);
    el marcador se busca después del modelo incrustado, y sin marcador en la plantilla, ValueError."""
    model, think_times, profile = small_inputs()
    # Un estado con é y un emoji, y el texto del marcador dentro del modelo general
    model = {**model, "note": "__GROUPS_JSON__"}
    group = {"weight": 1.0, "start": {"GET /a": 1.0}, "transitions": {"GET /a": {"GET /b": 1.0}},
             "status_transitions": {"GET /a": {"200": {"GET /b": 1.0}}},
             "think_time_ms": {"GET /a": {"GET /b": [1000]}}, "extra": "no va al JSON"}
    group["transitions"]["GET /caf\u00e9 \U0001F600"] = {END: 1.0}
    plan = tmp_path / "ascii.jmx"
    generate_jmx(copy.deepcopy(model), think_times, profile, str(plan), visit_groups=[group, group])
    script = jsr223_scripts(plan)[PICKER]
    expression = picker_expression(script)
    assert expression.isascii()
    data = picker_groups(script)
    assert data["groups"][0]["transitions"]["GET /caf\u00e9 \U0001F600"] == {END: 1.0}
    assert set(data["groups"][0]) == set(GROUP_KEYS)
    assert embedded_model(script)["note"] == "__GROUPS_JSON__"

    for missing in GROUP_KEYS:
        broken = {key: value for key, value in group.items() if key != missing}
        with pytest.raises(KeyError):
            generate_jmx(copy.deepcopy(model), think_times, profile, str(tmp_path / "broken.jmx"),
                         visit_groups=[broken])

    from jmx_generator import generator
    real = generator._groovy
    try:
        generator._groovy = lambda script, model_json: real("session_start.groovy", model_json)
        with pytest.raises(ValueError):
            generator._visit_group_script("{}", [group])
    finally:
        generator._groovy = real
