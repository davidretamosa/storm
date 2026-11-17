"""Grupos de visita (--visit-groups): la tabla de cada sesión, el KMeans y el plan (T-2.1), y las tres reglas
que juntan y validan los grupos (T-2.2).

Los logs sintéticos usan endpoints inventados (/a, /b...): la mejora no sabe nada de ninguna app.
"""
import json
import math
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

import sklearn.cluster
import sklearn.metrics

from bench.tests.support import BANKAPP, JAR, ROOT, generate, sha256
from log_parser.parser import parse_logs
from traffic_model import visit_groups
from traffic_model.markov import END
from traffic_model.visit_groups import (
    CREATES, FLOOR, FOLDS, LENGTH, MAX_GROUPS, MIN_GROUP, PAUSE, RATE_4XX, SAME_NAVIGATION, SEED, START,
    cluster_sessions, describe, find_visit_groups, group_labels, heldout_gain, js_distance, log_likelihood,
    merge_alike, navigation, session_table, split,
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


def test_flag_does_not_change_the_plan_yet(tmp_path):
    """PROVISIONAL (lo borra el T-2.4): con grupos, el .jmx aún no cambia."""
    plain = generate(["--logs", BANKAPP, "--session"], tmp_path / "plain.jmx")
    grouped = generate(["--logs", BANKAPP, "--session", "--visit-groups"], tmp_path / "grouped.jmx")
    assert sha256(plain) == sha256(grouped)


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
