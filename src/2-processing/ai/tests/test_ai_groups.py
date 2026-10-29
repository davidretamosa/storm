"""Grups de visita (--ai-groups, T-2): característiques, agrupament, les dues regles d'un sol grup i el pla.

Els logs sintètics fan servir endpoints inventats (/a, /b...): la millora no sap res de cap app.
"""
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from ai import jmx_post
from ai.enhancements.groups import NAME, SESSION_START, embedded_model
from ai.enhancements.groups_cluster import find_groups
from ai.enhancements.groups_features import session_features, session_steps
from ai.hooks import HookError
from ai.tests.support import AI, INPUTS, MAIN, ROOT, generate
from log_parser.parser import parse_logs

REFERENCE = "ai/bench/data/bankapp_vall_pic_3h.jsonl"
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def write_log(path, sessions):
    """sessions: [[(mètode, endpoint, codi, segons des de l'inici de la sessió), ...], ...], una cada minut."""
    lines = []
    for n, requests in enumerate(sessions):
        start = T0 + timedelta(minutes=n)
        for method, endpoint, status, seconds in requests:
            lines.append(json.dumps({
                "timestamp": (start + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z"),
                "sessionId": f"s{n}", "userId": 1, "method": method, "endpoint": endpoint, "path": endpoint,
                "status": status, "durationMs": 5, "body": None}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def visit(keys, pause, status=200):
    return [(*key.split(" "), status, i * pause) for i, key in enumerate(keys)]


def two_kinds(shared=True):
    """Dos tipus de visita. Amb `shared`, passen pels mateixos estats (/a i /b) i una sola cadena els barreja
    (genera /a /b /d, que no fa ningú); sense, no comparteixen res."""
    reader = [visit(["GET /a", "GET /b"], 2 + n % 3) for n in range(30)]
    writer = ["GET /a", "POST /c", "GET /b", "POST /d"] if shared else ["POST /c", "GET /d", "POST /c"]
    writers = [visit(writer, 3 + n % 4, status=201) for n in range(30)]
    return [s for pair in zip(reader, writers) for s in pair]


def one_kind_two_paces():
    return [visit(["GET /a", "GET /b", "GET /c"], 1 if n % 2 else 60) for n in range(60)]


def one_random_chain(n=400, seed=1):
    """Visites d'una sola cadena a l'atzar: un sol tipus, però amb seqüències molt diferents."""
    rng = np.random.default_rng(seed)
    keys = ["GET /a", "GET /b", "POST /c"]
    sessions = []
    for _ in range(n):
        sequence = [keys[rng.integers(3)]]
        while rng.random() < 0.6 and len(sequence) < 12:
            sequence.append(keys[rng.integers(3)])
        sessions.append(visit(sequence, 2))
    return sessions


# --- Característiques -------------------------------------------------------------------------------

def test_features_one_row_per_session(tmp_path):
    log = write_log(tmp_path / "log.jsonl", [visit(["GET /a", "GET /a", "POST /b"], 3, status=201),
                                              [("GET", "/a", 404, 0)]])
    steps, ids = session_steps(parse_logs(str(log)))
    matrix, names = session_features(steps, ids)
    row = dict(zip(names, matrix[0]))
    assert ids == ["s0", "s1"]
    assert (row["GET /a"], row["POST /b"], row["<longitud>"], row["<crea>"]) == (2, 1, 3, 1)
    assert row["<pausa_log>"] == pytest.approx(np.log1p(3))
    assert dict(zip(names, matrix[1]))["<taxa_4xx>"] == 1


# --- Agrupament i les regles d'un sol grup ----------------------------------------------------------

def test_two_clear_kinds_make_two_groups(tmp_path):
    df = parse_logs(str(write_log(tmp_path / "log.jsonl", two_kinds())))
    groups, report = find_groups(df, seed=0)
    assert len(set(groups.values())) == 2
    assert all(groups[f"s{n}"] == groups["s0"] for n in range(0, 60, 2))      # els lectors, junts
    assert all(groups[f"s{n}"] == groups["s1"] for n in range(1, 60, 2))      # els que creen, junts
    assert np.mean(report["heldout_gain"]) > 0


def test_kinds_with_nothing_in_common_need_no_groups(tmp_path):
    """Si dos tipus no comparteixen cap petició, una sola cadena ja els separa: els grups no hi afegeixen res
    (guany zero a la porta) i no es posen."""
    df = parse_logs(str(write_log(tmp_path / "log.jsonl", two_kinds(shared=False))))
    groups, report = find_groups(df, seed=0)
    assert np.mean(report["heldout_gain"]) == pytest.approx(0, abs=1e-4)
    assert set(groups.values()) == {0}


def test_one_kind_with_two_paces_merges_into_one_group(tmp_path):
    """Regla a): partir per la pausa no canvia la navegació; els grups es fusionen."""
    df = parse_logs(str(write_log(tmp_path / "log.jsonl", one_kind_two_paces())))
    groups, report = find_groups(df, seed=0)
    assert set(groups.values()) == {0}
    assert report["merges"]


def test_one_random_chain_is_one_group(tmp_path):
    """Regla b), el control de la consultora: una sola cadena a l'atzar fa grups que no prediuen millor."""
    df = parse_logs(str(write_log(tmp_path / "log.jsonl", one_random_chain())))
    groups, report = find_groups(df, seed=0)
    assert report["k"] > 1 and not report["merges"]      # l'agrupament sí que en troba...
    assert np.mean(report["heldout_gain"]) <= 0           # ...però no s'aguanten
    assert set(groups.values()) == {0}


def test_same_seed_same_groups(tmp_path):
    df = parse_logs(str(write_log(tmp_path / "log.jsonl", two_kinds())))
    assert find_groups(df, seed=3) == find_groups(df, seed=3)


def test_too_few_sessions_is_one_group(tmp_path):
    df = parse_logs(str(write_log(tmp_path / "log.jsonl", two_kinds()[:6])))
    groups, report = find_groups(df, seed=0)
    assert set(groups.values()) == {0} and "massa poques" in report["one_group"]


# --- El pla ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("sessions", [one_kind_two_paces, one_random_chain])
def test_one_kind_plan_is_the_plan_without_groups(sessions, tmp_path):
    log = write_log(tmp_path / "log.jsonl", sessions())
    main = generate(MAIN, ["--logs", str(log)], tmp_path / "main.jmx")
    groups = generate(AI, ["--ai-groups", "--logs", str(log)], tmp_path / "groups.jmx")
    assert jmx_post.canonical(groups) == jmx_post.canonical(main)


def test_jar_only_plan_is_the_plan_without_groups(reference_plans, tmp_path):
    plan = generate(AI, ["--ai-groups", *INPUTS["jar"]], tmp_path / "jar.jmx")
    assert jmx_post.canonical(plan) == jmx_post.canonical(reference_plans["jar"])


@pytest.fixture(scope="module")
def reference_groups_plan(tmp_path_factory):
    folder = tmp_path_factory.mktemp("groups")
    args = ["--logs", REFERENCE, "--session"]
    return generate(MAIN, args, folder / "main.jmx"), generate(AI, ["--ai-groups", *args], folder / "groups.jmx")


def _script(element):
    return element.find("stringProp[@name='script']").text


def test_plan_adds_only_the_group_picker(reference_groups_plan):
    main, groups = (jmx_post.read(p).getroot() for p in reference_groups_plan)
    pickers = [e for e in groups.iter("JSR223PreProcessor") if e.get("testname") == NAME]
    assert len(pickers) == 1
    # És el primer de «Nueva sesión», just abans del dels companys
    parent = jmx_post.parent_of(groups, pickers[0])
    children = [e.get("testname") for e in parent if e.tag != "hashTree"]
    assert children == [NAME, SESSION_START]
    # Tret d'això, el pla és el dels companys
    parent.remove(jmx_post.child_tree(groups, pickers[0]))
    parent.remove(pickers[0])
    assert ET.canonicalize(ET.tostring(groups, encoding="unicode")) == \
        ET.canonicalize(ET.tostring(main, encoding="unicode"))


def test_plan_group_models_fit_the_global_model(reference_groups_plan):
    root = jmx_post.read(reference_groups_plan[1]).getroot()
    picker = next(e for e in root.iter("JSR223PreProcessor") if e.get("testname") == NAME)
    start = next(e for e in root.iter("JSR223PreProcessor") if e.get("testname") == SESSION_START)
    script = _script(picker)
    # El model base és el mateix que porten els scripts dels companys
    assert embedded_model(script) == embedded_model(_script(start))
    base = json.loads(embedded_model(script))
    data = json.loads(script.split("parseText('''")[2].split("''')")[0])

    assert len(data["groups"]) == 7 and sum(data["weights"]) == pytest.approx(1)
    for group in data["groups"]:
        assert set(group) == {"start", "transitions", "think_time_ms"}
        assert set(group["start"]) | set(group["transitions"]) <= set(base["states"])
        for source, targets in group["transitions"].items():
            assert sum(targets.values()) == pytest.approx(1)
            assert set(targets) - {"END"} <= set(group["think_time_ms"].get(source, {}))


def test_plan_keeps_one_thread_group_and_vusers(reference_groups_plan):
    main, groups = (jmx_post.read(p).getroot() for p in reference_groups_plan)
    assert len(groups.findall(".//ThreadGroup")) == 1
    threads = ".//ThreadGroup/stringProp[@name='ThreadGroup.num_threads']"
    assert groups.find(threads).text == main.find(threads).text
    assert groups.find(threads).text.startswith("${__P(vusers,")


def test_embedded_model_fails_loud_without_model():
    with pytest.raises(HookError):
        embedded_model("vars.put('x', '1')")


# --- Contracte amb les plantilles dels companys --------------------------------------------------------

def test_contract_templates_read_storm_model_from_the_thread():
    """El selector de grup només funciona si els scripts dels companys llegeixen stormModel abans del model
    incrustat i en fan servir l'inici, les transicions i les pauses."""
    templates = ROOT / "jmx_generator" / "templates"
    common = (templates / "markov_common.groovy").read_text(encoding="utf-8")
    assert 'def model = vars.getObject("stormModel")\nif (model == null) {' in common
    assert "goTo(pick(model.start))" in (templates / "session_start.groovy").read_text(encoding="utf-8")
    following = (templates / "next_request.groovy").read_text(encoding="utf-8")
    assert "pick(model.transitions[current]" in following
    assert "model.think_time_ms[current]" in following


# --- El banc: recuperació, sessions senceres i el log d'un sol tipus ------------------------------------

def test_recovery_profiles_by_signature():
    from ai.bench.recovery import UNKNOWN, profile
    assert profile(["POST /api/users"]) == "nuevo_cliente:alta"
    assert profile(["POST /api/users"], whole=True) == "nuevo_cliente"
    assert profile(["GET /api/accounts/{id}", "POST /api/transfers", "GET /api/accounts/{id}/transactions",
                    "POST /api/accounts/{id}/withdraw"]) == "pagador"
    assert profile(["GET /x"]) == UNKNOWN


def test_session_js_is_zero_for_the_same_traffic_and_one_for_disjoint(tmp_path):
    from ai.bench import metrics
    from ai.bench.recovery import session_scores
    a = metrics.requests(parse_logs(str(write_log(tmp_path / "a.jsonl", two_kinds()))))
    b = metrics.requests(parse_logs(str(write_log(tmp_path / "b.jsonl", [visit(["GET /z"], 1)] * 20))))
    assert session_scores(a, a) == {"session_js": 0.0, "session_length_wasserstein": 0.0, "session_length_ks": 0.0}
    assert session_scores(a, b)["session_js"] == pytest.approx(1)


def test_one_type_log_keeps_sessions_and_is_reproducible(tmp_path):
    from ai.bench.one_type_log import one_type_log
    log = write_log(tmp_path / "log.jsonl", two_kinds())
    first, again = one_type_log(str(log), seed=0), one_type_log(str(log), seed=0)
    assert first == again
    assert {l["sessionId"] for l in first} == {f"s{n}" for n in range(60)}
    timestamps = [l["timestamp"] for l in first]
    assert timestamps == sorted(timestamps)
    # Una sola cadena: surten seqüències que cap dels dos tipus no fa
    sequences = {}
    for line in first:
        sequences.setdefault(line["sessionId"], []).append(f"{line['method']} {line['endpoint']}")
    known = {("GET /a", "GET /b"), ("GET /a", "POST /c", "GET /b", "POST /d")}
    assert {tuple(s) for s in sequences.values()} - known
