"""La millora del trànsit habitual (T-1, --ai-traffic). Logs sintètics fets aquí mateix: cap dada real."""
import json
from collections import Counter
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from ai import jmx_post
from ai.bench import jmeter
from ai.enhancements import traffic, traffic_curve, traffic_stats
from ai.enhancements.base import Context
from ai.tests.support import AI, INPUTS, ROOT, generate
from log_parser.parser import parse_logs
from traffic_model.payloads import build_path_params
from traffic_model.think_time import build_think_times

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def in_processing(monkeypatch):
    monkeypatch.chdir(ROOT)


def line(second, session, endpoint="/api/accounts/{id}", path="/api/accounts/1", method="GET", status=200,
         duration=None, user=1):
    entry = {"timestamp": (T0 + timedelta(seconds=second)).isoformat().replace("+00:00", "Z"),
             "sessionId": session, "userId": user, "method": method, "endpoint": endpoint, "path": path,
             "status": status}
    if duration is not None:
        entry["durationMs"] = duration
    return entry


def write_log(tmp_path, entries, name="log.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def read(tmp_path, entries):
    return parse_logs(str(write_log(tmp_path, entries)))


# --- traffic_stats: pauses netes ------------------------------------------------------------------

def pauses_of(df):
    return df.groupby("session_id")["timestamp"].diff().dt.total_seconds().dropna().tolist()


def test_net_pauses_subtract_the_response_time_of_the_request_that_closes_the_gap(tmp_path):
    """L'app apunta l'hora en ACABAR la petició: el forat fins a una línia porta la duració d'aquella línia."""
    df = read(tmp_path, [line(0, "s1", duration=500), line(3, "s1", duration=200), line(4, "s1", duration=9)])
    net = traffic_stats.net_pauses(df)
    assert pauses_of(net) == pytest.approx([2.8, 0.991])          # 3 - 0,2 i 1 - 0,009 (els 500 ms de la primera no)
    assert net["timestamp"].iloc[0] == df["timestamp"].iloc[0]   # la sessió comença on començava


def test_net_pauses_never_go_negative(tmp_path):
    """Una petició que triga més que el forat que tanca: la pausa és 0, no negativa."""
    df = read(tmp_path, [line(0, "s1"), line(1, "s1", duration=5000), line(2, "s1")])
    assert pauses_of(traffic_stats.net_pauses(df)) == [0.0, 1.0]


def test_a_negative_duration_does_not_lengthen_a_pause(tmp_path):
    df = read(tmp_path, [line(0, "s1"), line(5, "s1", duration=-3000), line(6, "s1", duration=100)])
    assert pauses_of(traffic_stats.net_pauses(df)) == pytest.approx([5.0, 0.9])


def test_net_pauses_reach_the_think_times_of_the_team(tmp_path):
    df = read(tmp_path, [line(0, "s1", duration=300), line(5, "s1", "/api/users/{id}", "/api/users/1", duration=1000)])
    original = build_think_times(df)["GET /api/accounts/{id}"]["GET /api/users/{id}"]
    net = build_think_times(traffic_stats.net_pauses(df))["GET /api/accounts/{id}"]["GET /api/users/{id}"]
    assert set(original) == {5000} and set(net) == {4000}


def test_net_pauses_keep_sessions_apart_and_leave_the_input_alone(tmp_path):
    df = read(tmp_path, [line(0, "a"), line(1, "b"), line(2, "a", duration=100), line(3, "b", duration=900)])
    before = df.copy()
    net = traffic_stats.net_pauses(df)
    gaps = {s: g["timestamp"].diff().dt.total_seconds().dropna().tolist() for s, g in net.groupby("session_id")}
    assert gaps == {"a": [1.9], "b": [1.1]}
    pd.testing.assert_frame_equal(df, before)


def test_net_pauses_with_a_repeated_index(tmp_path):
    """Dos logs enganxats amb pd.concat repeteixen l'índex: el resultat és el mateix i l'índex es conserva."""
    first = read(tmp_path, [line(0, "a"), line(2, "a", duration=500)])
    second = read(tmp_path, [line(10, "b"), line(14, "b", duration=1000)])
    df = pd.concat([first, second])
    net = traffic_stats.net_pauses(df)
    assert list(net.index) == list(df.index)
    assert pauses_of(net) == pytest.approx([1.5, 3.0])


def test_without_durations_the_log_is_untouched(tmp_path):
    df = read(tmp_path, [line(0, "s1"), line(3, "s1")])
    assert traffic_stats.net_pauses(df) is df


# --- traffic_stats: errors ------------------------------------------------------------------------

def test_path_ids_are_learned_only_from_successful_requests(tmp_path):
    df = read(tmp_path, [line(0, "s1", path="/api/accounts/1"), line(1, "s1", path="/api/accounts/2"),
                         line(2, "s1", path="/api/accounts/999", status=404)])
    with_404 = build_path_params(df)["GET /api/accounts/{id}"]["id"]
    clean = build_path_params(traffic_stats.successful(df))["GET /api/accounts/{id}"]["id"]
    assert "999" in [v for v, _ in with_404]                  # sense la millora, el 404 s'hi cola
    assert sorted(v for v, _ in clean) == ["1", "2"]


def test_a_request_with_no_success_keeps_its_ids(tmp_path):
    """Si una petició no ha anat bé mai, no es filtra: si no, sortiria del pla i JMeter posaria un 1."""
    df = read(tmp_path, [line(0, "s1", "/api/users/{id}", "/api/users/7", status=404),
                         line(1, "s1", path="/api/accounts/1")])
    params = build_path_params(traffic_stats.successful(df))
    assert params["GET /api/users/{id}"]["id"] == [["7", 1.0]]


def test_a_line_without_status_is_kept(tmp_path):
    """No se sap si va fallar: no es llença."""
    entries = [line(0, "s1", path="/api/accounts/1"), line(1, "s1", path="/api/accounts/5"),
               line(2, "s1", path="/api/accounts/999", status=404)]
    del entries[1]["status"]
    clean = build_path_params(traffic_stats.successful(read(tmp_path, entries)))["GET /api/accounts/{id}"]["id"]
    assert sorted(v for v, _ in clean) == ["1", "5"]


def test_a_304_is_a_failure(tmp_path):
    """El filtre és estricte: el que no és 2xx no ensenya ids (un 304 tampoc)."""
    df = read(tmp_path, [line(0, "s1", path="/api/accounts/1"), line(1, "s1", path="/api/accounts/3", status=304)])
    clean = build_path_params(traffic_stats.successful(df))["GET /api/accounts/{id}"]["id"]
    assert [v for v, _ in clean] == ["1"]


def test_without_status_nothing_is_filtered(tmp_path):
    entries = [line(0, "s1"), line(1, "s1", path="/api/accounts/2")]
    for entry in entries:
        del entry["status"]
    df = read(tmp_path, entries)
    assert traffic_stats.successful(df) is df
    assert traffic_stats.error_rates(df) == {}


def test_error_rates(tmp_path):
    df = read(tmp_path, [line(0, "s1"), line(1, "s1", status=404), line(2, "s1", status=503),
                         line(3, "s1", status=201), line(4, "s1", "/api/users", "/api/users", "POST")])
    assert traffic_stats.error_rates(df) == {
        "GET /api/accounts/{id}": {"requests": 4, "4xx": 0.25, "5xx": 0.25},
        "POST /api/users": {"requests": 1, "4xx": 0.0, "5xx": 0.0},
    }


def test_reference_durations(tmp_path):
    df = read(tmp_path, [line(i, "s1", duration=d) for i, d in enumerate(range(1, 21))])   # 1..20 ms
    durations = traffic_stats.reference_durations(df)["GET /api/accounts/{id}"]
    assert durations == {"requests": 20, "p50_ms": 10.5, "p95_ms": 19.05}


# --- traffic_curve: la corba ---------------------------------------------------------------------

def valley_peak_valley(tmp_path):
    """3 hores: 1 sessió oberta a cada moment, després 3 alhora, després 1 (sessions de 10 min)."""
    entries = []
    for hour, parallel in enumerate([1, 3, 1]):
        for k in range(6):                       # 6 franges de 10 min per hora
            start = hour * 3600 + k * 600
            for p in range(parallel):
                session = f"h{hour}-{k}-{p}"
                entries += [line(start, session), line(start + 599, session)]
    return read(tmp_path, entries)


def test_the_curve_follows_the_open_sessions(tmp_path):
    curve = traffic_curve.concurrency_curve(valley_peak_valley(tmp_path))
    assert curve["slice_seconds"] == pytest.approx(10799 / 18) and len(curve["values"]) == 18
    assert curve["values"][:6] == pytest.approx([1 / 3] * 6, abs=1e-3)
    assert curve["values"][6:12] == pytest.approx([1] * 6, abs=1e-3)
    assert curve["values"][12:] == pytest.approx([1 / 3] * 6, abs=1e-3)
    assert curve["start"] == "2026-01-01T09:00:00+00:00"


def test_a_long_log_widens_the_slices(tmp_path):
    df = read(tmp_path, [line(0, "a"), line(3 * 24 * 3600, "a")])     # una sessió de 3 dies
    curve = traffic_curve.concurrency_curve(df)
    assert len(curve["values"]) == traffic_curve.MAX_SLICES
    assert curve["slice_seconds"] == pytest.approx(3 * 24 * 3600 / traffic_curve.MAX_SLICES)


@pytest.mark.parametrize("span", [599, 601, 3601])
def test_the_last_slice_is_not_a_leftover(tmp_path, span):
    """Sessions obertes tot el log: la corba és plana, encara que el log no duri un múltiple de 10 minuts.
    (Abans, amb 601 s, l'última franja valia 0,0017: la meitat de la prova sense cap fil; ho va trobar el
    verificador el 2026-10-29.)"""
    df = read(tmp_path, [line(t, s) for s in "abc" for t in (0, span)])
    curve = traffic_curve.concurrency_curve(df)
    assert curve["values"] == [1.0] * len(curve["values"])
    assert curve["slice_seconds"] * len(curve["values"]) == pytest.approx(span)


def test_single_request_sessions_still_count(tmp_path):
    df = read(tmp_path, [line(0, "a"), line(700, "b"), line(710, "c")])
    assert traffic_curve.concurrency_curve(df)["values"] == [0.5, 1.0]


def test_no_sessions_no_curve(tmp_path):
    assert traffic_curve.concurrency_curve(None) is None
    df = read(tmp_path, [line(0, "a")])
    assert traffic_curve.concurrency_curve(df.assign(session_id=None)) is None
    assert traffic_curve.concurrency_curve(df.assign(session_id="")) is None


def test_the_empty_session_is_not_a_session(tmp_path):
    """bankapp.jsonl porta "" als login i logout: comptada, seria una sessió de tot el log que aixeca les valls.
    (La va trobar el verificador el 2026-10-29.)"""
    with_empty = valley_peak_valley(tmp_path)
    loose = read(tmp_path, [line(0, ""), line(10799, "")])
    curve = traffic_curve.concurrency_curve(pd.concat([with_empty, loose], ignore_index=True))
    assert curve == traffic_curve.concurrency_curve(with_empty)


def test_the_timer_carries_the_curve_and_is_off_by_default():
    element, tree = traffic_curve.timer({"values": [0.25, 1.0]})
    assert element.tag == "JSR223Timer" and tree.tag == "hashTree"
    script = element.find("stringProp[@name='script']").text
    assert "double[] curve = [0.25, 1.0] as double[]" in script
    assert 'props.getProperty("curva_horaria", "0").trim() != "1"' in script
    assert script.index("curva_horaria") < script.index("curve =")   # apagada abans de fer res
    # un fil que ja no ha de treballar s'atura: si esperés al final, JMeter el despertaria per fer una última
    # sessió (tots alhora; vist al JMeter real el 2026-10-29)
    assert script.rstrip().endswith("ctx.getThread().stop()\nreturn 0L")
    assert element.find("stringProp[@name='scriptLanguage']").text == "groovy"


def test_the_timer_goes_into_the_session_start(reference_plans):
    root = jmx_post.read(reference_plans["bankapp+session"]).getroot()
    traffic_curve.add_timer(root, {"values": [1.0]})
    action = root.find(".//TestAction")
    children = list(jmx_post.child_tree(root, action))
    assert [c.tag for c in children] == ["JSR223PreProcessor", "hashTree", "JSR223Timer", "hashTree"]
    assert children[2].get("testname") == traffic_curve.TIMER_NAME


def test_a_plan_without_session_start_fails_hard(reference_plans):
    root = jmx_post.read(reference_plans["logs"]).getroot()
    action = root.find(".//TestAction")
    jmx_post.parent_of(root, action).remove(action)
    with pytest.raises(ValueError, match="TestAction"):
        traffic_curve.add_timer(root, {"values": [1.0]})


def test_without_the_curve_in_the_plan_the_side_file_goes(tmp_path, reference_plans):
    """Si la corba no es pot posar, no queda un .ai.json que digui que s'encén amb -Jcurva_horaria=1."""
    root = jmx_post.read(reference_plans["logs"]).getroot()
    action = root.find(".//TestAction")
    jmx_post.parent_of(root, action).remove(action)
    enhancement = traffic.Enhancement(Context())
    enhancement.curve = {"values": [1.0]}
    enhancement.side_path = tmp_path / "plan.jmx.ai.json"
    enhancement.side_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        enhancement.edit_jmx(root)
    assert not enhancement.side_path.exists()


# --- traffic_curve: el temporitzador, amb el JMeter de debò ---------------------------------------

SLICE = 6   # s de prova per franja
ELAPSED = ("SampleResult.setSampleLabel(String.valueOf(System.currentTimeMillis() - "
           "org.apache.jmeter.threads.JMeterContextService.getTestStartTime())); ")


def timer_plan(path, values, threads):
    """Pla mínim: ThreadGroup → «Nueva sesión» (amb el temporitzador) → un sampler d'1 s que no surt de la màquina.
    (Basat en el pla del verificador del 2026-10-29.)"""
    plan = ET.Element("jmeterTestPlan", version="1.2", properties="5.0", jmeter="5.6.3")
    top = ET.SubElement(plan, "hashTree")
    ET.SubElement(top, "TestPlan", guiclass="TestPlanGui", testclass="TestPlan", testname="corba")
    plan_tree = ET.SubElement(top, "hashTree")
    group = ET.SubElement(plan_tree, "ThreadGroup", guiclass="ThreadGroupGui", testclass="ThreadGroup", testname="G")
    loop = ET.SubElement(group, "elementProp", name="ThreadGroup.main_controller", elementType="LoopController",
                         guiclass="LoopControlPanel", testclass="LoopController")
    ET.SubElement(loop, "boolProp", name="LoopController.continue_forever").text = "false"
    ET.SubElement(loop, "intProp", name="LoopController.loops").text = "-1"
    for name, value in [("on_sample_error", "continue"), ("num_threads", str(threads)), ("ramp_time", "0"),
                        ("duration", str(SLICE * len(values))), ("delay", "0")]:
        ET.SubElement(group, "stringProp", name=f"ThreadGroup.{name}").text = value
    ET.SubElement(group, "boolProp", name="ThreadGroup.scheduler").text = "true"
    group_tree = ET.SubElement(plan_tree, "hashTree")
    action = ET.SubElement(group_tree, "TestAction", guiclass="TestActionGui", testclass="TestAction",
                           testname="Nueva sesión")
    ET.SubElement(action, "intProp", name="ActionProcessor.action").text = "1"
    ET.SubElement(action, "intProp", name="ActionProcessor.target").text = "0"
    ET.SubElement(action, "stringProp", name="ActionProcessor.duration").text = "0"
    ET.SubElement(group_tree, "hashTree").extend(traffic_curve.timer({"values": values}))
    sampler = ET.SubElement(group_tree, "JSR223Sampler", guiclass="TestBeanGUI", testclass="JSR223Sampler",
                            testname="trabajo")
    for name, value in [("scriptLanguage", "groovy"), ("parameters", ""), ("filename", ""), ("cacheKey", "true"),
                        ("script", ELAPSED + "Thread.sleep(1000); SampleResult.setResponseCode('200'); return 'ok'")]:
        sampler.append(jmx_post.string_prop(name, value))
    ET.SubElement(group_tree, "hashTree")
    ET.ElementTree(plan).write(path, encoding="UTF-8", xml_declaration=True)
    return path


def run_timer_plan(folder, properties, values, threads):
    """Les mostres del pla mínim: (segon de prova segons el rellotge del temporitzador, fil), sense errors al log."""
    plan = timer_plan(folder / "plan.jmx", values, threads)
    code, output = jmeter.run(plan, folder / "r.jtl", folder / "j.log", properties)
    assert code == 0, output
    log = (folder / "j.log").read_text(encoding="utf-8")
    assert " ERROR " not in log, log
    samples = jmeter.read_jtl(folder / "r.jtl")
    seconds = samples["label"].astype(int) / 1000
    numbers = [int(name.rsplit("-", 1)[1]) - 1 for name in samples["threadName"]]   # «G 1-3» → fil 2
    return list(zip(seconds, numbers))


def threads_per_slice(folder, properties, values, threads):
    """{franja: fils que hi han treballat}, comptant només el mig de cada franja (marges d'1,5 s a cada costat).
    L'hora de cada mostra és la del rellotge del temporitzador (getTestStartTime), que el sampler posa a l'etiqueta."""
    working = {j: set() for j in range(len(values))}
    for at, thread in run_timer_plan(folder, properties, values, threads):
        j, inside = divmod(at, SLICE)
        if 1.5 <= inside <= SLICE - 1.5 and int(j) in working:
            working[int(j)].add(thread)
    return working


needs_jmeter = pytest.mark.skipif(not jmeter.jmeter_binary().exists(), reason="no hi ha JMeter local")
CURVE = [1.0, 0.25, 0.0, 0.5]


@needs_jmeter
@pytest.mark.parametrize("value", [None, "0", "true"])
def test_real_jmeter_curve_is_off_unless_asked(tmp_path, value):
    """Sense -Jcurva_horaria=1 treballen tots els fils tota la prova (el pic constant del laboratori)."""
    properties = {} if value is None else {traffic_curve.PROPERTY: value}
    working = threads_per_slice(tmp_path, properties, CURVE, 4)
    assert working == {j: {0, 1, 2, 3} for j in range(4)}


@needs_jmeter
def test_real_jmeter_follows_the_curve(tmp_path):
    """Amb 4 fils i la corba [1, 0,25, 0, 0,5]: 4 fils, després només el 0, després cap, després el 0 i l'1."""
    working = threads_per_slice(tmp_path, {traffic_curve.PROPERTY: "1"}, CURVE, 4)
    assert working == {0: {0, 1, 2, 3}, 1: {0}, 2: set(), 3: {0, 1}}


@needs_jmeter
def test_real_jmeter_the_border_thread_works_with_the_decimal_part(tmp_path):
    """0,4 × 4 fils = 1,6: el fil 0 sempre, el 2 i el 3 mai, i l'1 (la frontera) treballa una sessió amb
    probabilitat 0,6; quan perd, dorm fins a la franja següent. Fa, doncs, moltes menys sessions que el 0
    (~6 contra ~24). Si treballés sempre (Math.round, o sense sorteig) en faria tantes com el 0; si no
    treballés mai, no hi seria."""
    sessions = Counter(thread for _, thread in run_timer_plan(tmp_path, {traffic_curve.PROPERTY: "1"}, [0.4] * 4, 4))
    assert set(sessions) == {0, 1}
    assert sessions[1] < 0.75 * sessions[0], sessions


# --- traffic: la millora sencera, sobre les 5 entrades de la prova d'identitat ----------------------

TIMER_TEXT = 'Long.parseLong(vars.get("stormThinkMs") ?: "0")'   # contracte amb el laboratori (factor_pausa)


def models_of(root):
    """Els JSON del model que viatgen dins dels scripts Groovy (jmx_generator/generator.py:_groovy), tots."""
    models = []
    for prop in root.iter("stringProp"):
        if prop.get("name") == "script" and "parseText('''" in (prop.text or ""):
            embedded = prop.text.split("parseText('''", 1)[1].split("''')", 1)[0]
            models.append(json.loads(embedded.replace("\\'\\'\\'", "'''").replace("\\\\", "\\")))
    assert models, "el pla no porta el model"
    return models


def without_model(root):
    """El .jmx canònic, sense el temporitzador de la corba i amb el JSON del model tret de tots els scripts."""
    for parent in root.iter():
        for child in list(parent):
            if child.get("testname") == traffic_curve.TIMER_NAME:
                index = list(parent).index(child)
                parent.remove(parent[index + 1])   # el seu <hashTree/>
                parent.remove(child)
    for prop in root.iter("stringProp"):
        if prop.get("name") == "script" and "parseText('''" in (prop.text or ""):
            head, rest = prop.text.split("parseText('''", 1)
            prop.text = head + "parseText('''MODEL''')" + rest.split("''')", 1)[1]
    return jmx_post.canonical(ET.tostring(root, encoding="unicode"))


@pytest.fixture(scope="module")
def traffic_plans(tmp_path_factory):
    folder = tmp_path_factory.mktemp("traffic")
    return {name: generate(AI, ["--ai-traffic", *args], folder / f"{name}.jmx") for name, args in INPUTS.items()}


@pytest.mark.parametrize("name", INPUTS)
def test_load_is_the_same(name, traffic_plans, reference_plans):
    """vusers, rampa i durada idèntics: la corba no puja mai del pic, només adorm fils (i va apagada)."""
    props = ("num_threads", "ramp_time", "duration", "scheduler", "delay")
    def thread_group(plan):
        group = jmx_post.read(plan).getroot().find(".//ThreadGroup")
        return {p: group.find(f"*[@name='ThreadGroup.{p}']").text for p in props}
    assert thread_group(traffic_plans[name]) == thread_group(reference_plans[name])


@pytest.mark.parametrize("name", INPUTS)
def test_only_pauses_and_path_ids_change_in_the_model(name, traffic_plans, reference_plans):
    """El que fan les altres millores (Markov, bodies, correlació, sessió) no canvia amb --ai-traffic."""
    all_ours = models_of(jmx_post.read(traffic_plans[name]).getroot())
    all_theirs = models_of(jmx_post.read(reference_plans[name]).getroot())
    assert len(all_ours) == len(all_theirs)
    for ours, theirs in zip(all_ours, all_theirs):
        changed = {key for key in theirs if ours.get(key) != theirs[key]} | (set(ours) - set(theirs))
        assert changed <= {"think_time_ms", "path_params"}
        for source, targets in theirs["think_time_ms"].items():     # pauses netes: mai més llargues
            for target, pauses in targets.items():
                assert all(a <= b for a, b in zip(ours["think_time_ms"][source][target], pauses))


@pytest.mark.parametrize("name", INPUTS)
def test_the_rest_of_the_plan_is_the_same(name, traffic_plans, reference_plans):
    ours = jmx_post.read(traffic_plans[name]).getroot()
    assert without_model(ours) == without_model(jmx_post.read(reference_plans[name]).getroot())
    timers = [t for t in ours.iter("JSR223Timer") if t.get("testname") != traffic_curve.TIMER_NAME]
    assert [t.find("stringProp[@name='script']").text for t in timers] == [TIMER_TEXT]


@pytest.mark.parametrize("name", INPUTS)
def test_the_curve_is_there_when_the_log_has_sessions(name, traffic_plans):
    root = jmx_post.read(traffic_plans[name]).getroot()
    curves = [t for t in root.iter("JSR223Timer") if t.get("testname") == traffic_curve.TIMER_NAME]
    assert len(curves) == (0 if name == "jar" else 1)


def test_the_side_file(traffic_plans):
    data = json.loads(traffic.side_file(traffic_plans["bankapp+session"]).read_text(encoding="utf-8"))
    assert data["curve_property"] == "-Jcurva_horaria=1"
    assert max(data["curve"]["values"]) == 1.0
    assert data["reference_durations"] and data["error_rates"]
    assert all(set(v) == {"requests", "p50_ms", "p95_ms"} for v in data["reference_durations"].values())
    jar_only = json.loads(traffic.side_file(traffic_plans["jar"]).read_text(encoding="utf-8"))
    assert jar_only["curve"] is None and jar_only["reference_durations"] == {}
