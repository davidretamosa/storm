"""Bodies realistes (T-3, --ai-bodies): les regles apreses, el .jar, el Groovy del PreProcessor i la xarxa.

S'executen des de src/2-processing: `python -m pytest ai/tests/test_ai_bodies.py`.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

from ai import jmx_post
from ai.bench import jmeter
from ai.bench.bankapp import free_port
from ai.enhancements import bodies, bodies_jar, bodies_learn
from ai.enhancements.base import Context
from ai.tests.support import AI, JAR, LOG, ROOT, generate
from log_parser.parser import parse_logs
from traffic_model.payloads import build_body_models

REFERENCE = "ai/bench/data/bankapp_vall_pic_3h.jsonl"   # el log de referència del T-BASE
FIXTURE_JAR = ROOT / "ai/tests/data/bodies_fixture.jar"
GROOVY_LIB = jmeter.jmeter_binary().parent.parent / "lib"


def frame(rows):
    """DataFrame com el de parse_logs amb només el que fan servir les regles."""
    return pd.DataFrame([{"method": "POST", "endpoint": "/items", **row} for row in rows])


def build_with_layer(df, endpoints=None, jar_path=None):
    """La capa de --ai-bodies sobre build_body_models, sense passar per main.py."""
    enhancement = bodies.Enhancement(Context())
    enhancement.jar_path = jar_path
    return enhancement.build_body_models(build_body_models, df, endpoints), enhancement


# ---------------------------------------------------------------------------
# 1. Només les peticions que van anar bé
# ---------------------------------------------------------------------------

def test_successful_keeps_only_2xx():
    df = frame([{"status": 200, "body": {}}, {"status": 201, "body": {}}, {"status": 400, "body": {}},
                {"status": 500, "body": {}}])
    assert list(bodies_learn.successful(df)["status"]) == [200, 201]


def test_failed_requests_leave_the_numeric_range():
    """samples/access_sample.log: 3 retirades amb 400, una de 4.917,51. Predicció: el màxim baixa a 188,05."""
    df = parse_logs(LOG)
    request = "POST /api/accounts/{id}/withdraw"
    assert build_body_models(df)[request]["amount"]["max"] == 4917.51
    model, _ = build_with_layer(df)
    assert model[request]["amount"]["max"] == 188.05


def test_a_request_with_only_failed_bodies_keeps_its_model():
    df = frame([{"status": 400, "body": {"size": 3}}, {"status": 400, "body": {"size": 5}}])
    model, _ = build_with_layer(df)
    assert model == build_body_models(df)


# ---------------------------------------------------------------------------
# 2. Les regles: quantils, «diferent» i «únic»
# ---------------------------------------------------------------------------

def test_quantile_table_goes_from_min_to_max():
    table = bodies_learn.quantile_table(list(range(1, 101)))
    assert len(table) == 21 and table[0] == 1 and table[-1] == 100
    assert table == sorted(table) and table[10] == 50.5


def ids(pairs):
    return [{"sourceId": a, "targetId": b} for a, b in pairs]


def test_different_is_learned_when_chance_would_make_them_equal():
    never_equal = ids([(a, b) for a in (1, 2, 3) for b in (1, 2, 3) if a != b] * 10)   # 60 parells
    assert bodies_learn.different_pairs(never_equal) == [["sourceId", "targetId"]]


def test_different_is_not_learned_when_they_sometimes_match():
    independent = ids([(a, b) for a in (1, 2, 3) for b in (1, 2, 3)] * 10)
    assert bodies_learn.different_pairs(independent) == []


def test_different_needs_enough_evidence():
    """6 parells amb 3 valors: per atzar s'esperarien 2 coincidències; que no n'hi hagi no vol dir res."""
    few = ids([(1, 2), (2, 3), (3, 1), (1, 3), (2, 1), (3, 2)])
    assert bodies_learn.expected_matches([1, 2, 3, 1, 2, 3], [2, 3, 1, 3, 1, 2]) == pytest.approx(2)
    assert bodies_learn.different_pairs(few) == []


def test_different_ignores_fields_that_never_share_values():
    disjoint = ids([(a, b) for a in (1, 2, 3) for b in (7, 8, 9)] * 10)
    assert bodies_learn.different_pairs(disjoint) == []


def test_unique_learns_the_form_without_copying_values():
    values = [f"user{n}@mail.test" for n in range(25)]
    forms = bodies_learn.unique_fields([{"contact": v, "kind": "a"} for v in values])
    assert forms == {"contact": {"prefix": "user", "suffix": "@mail.test"}}


def test_unique_needs_enough_values_and_no_repeats():
    assert bodies_learn.unique_fields([{"code": f"c{n}"} for n in range(19)]) == {}      # un menys del mínim
    assert list(bodies_learn.unique_fields([{"code": f"c{n}"} for n in range(20)])) == ["code"]
    assert bodies_learn.unique_fields([{"code": f"c{n % 20}"} for n in range(25)]) == {}
    assert bodies_learn.unique_fields([{"code": f"c{n}"} for n in range(25)] + [{"code": "c0"}]) == {}  # un sol repetit
    assert bodies_learn.unique_fields([{"code": n} for n in range(25)]) == {}                          # no són textos


def test_unique_leaves_id_fields_alone():
    """Un id de text que no es repeteix (p. ej. UUID) l'ha de donar l'app, no l'inventa el pla."""
    bodies = [{"ownerId": f"00000000-0000-0000-0000-{n:012d}", "code": f"r{n}"} for n in range(25)]
    assert list(bodies_learn.unique_fields(bodies)) == ["code"]


def test_text_form():
    assert bodies_learn.text_form(["ana1@x.test", "pere7@x.test"]) == {"prefix": "storm-", "suffix": "@x.test"}
    assert bodies_learn.text_form(["ref-001", "ref-002"]) == {"prefix": "ref-00", "suffix": ""}
    assert bodies_learn.text_form(["a@one.test", "b@two.test"]) == {"prefix": "storm-", "suffix": ""}
    assert bodies_learn.text_form(["${x}1", "${x}2"]) == {"prefix": "storm-", "suffix": ""}   # JMeter ho interpretaria
    assert bodies_learn.text_form(["a1${x}", "b2${x}"]) == {"prefix": "storm-", "suffix": ""}
    assert bodies_learn.text_form(["ana.x@mail.test", "pep.x@mail.test"]) == {"prefix": "storm-",
                                                                              "suffix": "@mail.test"}  # només el domini


def test_fixed_value_has_the_form_and_the_length():
    assert bodies_learn.fixed_value({"prefix": "storm.", "suffix": "@example.com"}) == "storm.storm@example.com"
    assert bodies_learn.fixed_value({"prefix": "storm-nick-", "suffix": "", "max": 8}) == "stostorm"
    assert len(bodies_learn.fixed_value({"prefix": "storm.", "suffix": "@example.com", "max": 20})) == 20
    assert bodies_learn.fixed_value({"prefix": "p-", "suffix": "", "min": 10}) == "p-xxxstorm"


def test_unique_values_from_the_log_do_not_reach_the_plan():
    df = frame([{"status": 201, "body": {"code": f"person{n}@corp.test", "kind": "a"}} for n in range(25)])
    model, enhancement = build_with_layer(df)
    assert enhancement.rules["POST /items"]["unique"] == {"code": {"prefix": "person", "suffix": "@corp.test"}}
    assert model["POST /items"]["code"]["values"] == [["personstorm@corp.test", 1.0]]
    assert "person3@corp.test" in json.dumps(build_body_models(df))      # el model dels companys sí que els porta


def test_quantiles_come_only_from_successful_requests():
    """samples/access_sample.log: el darrer quantil de la retirada és el màxim de les 2xx (188,05), no 4.917,51."""
    _, enhancement = build_with_layer(parse_logs(LOG))
    assert enhancement.rules["POST /api/accounts/{id}/withdraw"]["numbers"]["amount"]["q"][-1] == 188.05


def test_rules_on_the_reference_log():
    """Predicció: quantils per als 3 imports, «diferent» només a la transferència i cap camp únic."""
    df = parse_logs(str(ROOT / REFERENCE))
    model, enhancement = build_with_layer(df)
    rules = enhancement.rules
    assert set(rules) == {"POST /api/accounts/{id}/deposit", "POST /api/accounts/{id}/withdraw",
                          "POST /api/transfers"}
    assert all(list(rule["numbers"]) == ["amount"] for rule in rules.values())
    assert rules["POST /api/transfers"]["different"] == [["fromAccountId", "toAccountId"]]
    assert not any(rule["unique"] for rule in rules.values())
    # sense .jar, les altes es queden com les deixen els companys (body buit)
    assert model["POST /api/users"] == {} and model["POST /api/accounts"] == {}


# ---------------------------------------------------------------------------
# 3. El body des del DTO del .jar (fixture genèric, ai/tests/data/bodies_fixture)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fixture_classes():
    return bodies_jar.read_classes(FIXTURE_JAR)


def test_reads_field_annotations(fixture_classes):
    fields = {f["name"]: f for f in fixture_classes["com.example.SignupForm"]["fields"]}
    assert [a["type"] for a in fields["handle"]["annotations"]] == [
        "jakarta.validation.constraints.NotBlank", "jakarta.validation.constraints.Size"]
    assert fields["KIND"]["static"]


def test_unique_comes_from_the_entity(fixture_classes):
    """Draft també té @Column(unique) a "handle", però no és @Entity: no compta."""
    assert bodies_jar.unique_names(fixture_classes) == {"contact", "slogan", "nick"}


SIGNUP_FIELDS = ["handle", "contact", "motto", "fee", "seats", "floor500", "tiny", "slogan", "nick", "groupId"]


def test_dto_body_respects_the_validations(fixture_classes):
    model, unique = bodies_jar.dto_body(fixture_classes, "com.example.SignupForm",
                                        bodies_jar.unique_names(fixture_classes))
    assert list(model) == SIGNUP_FIELDS        # sense id (READ_ONLY), KIND (static) ni tags (llista)
    handle = model["handle"]["values"][0][0]
    assert 3 <= len(handle) <= 12
    assert model["contact"]["values"][0][0] == "storm.storm@example.com"
    assert len(model["motto"]["values"][0][0]) >= 20
    assert (model["fee"]["min"], model["fee"]["max"]) == (1, 9.99)            # DecimalMax(10) exclusiu
    assert (model["floor500"]["min"], model["floor500"]["max"]) == (500, 599)  # el rang per defecte puja
    assert (model["tiny"]["min"], model["tiny"]["max"]) == (0.01, 0.5)         # @Positive + DecimalMax(0.5)
    assert model["seats"]["min"] >= 1
    assert unique == {"contact": {"prefix": "storm.", "suffix": "@example.com"},
                      "slogan": {"prefix": "storm-slogan-", "suffix": "", "min": 40},
                      "nick": {"prefix": "storm-nick-", "suffix": "", "max": 8}}
    model = {"POST /x": model}
    bodies.hide_unique_values(model, {"POST /x": {"unique": unique}})
    assert len(model["POST /x"]["nick"]["values"][0][0]) <= 8          # el valor de reserva també respecta @Size
    assert len(model["POST /x"]["slogan"]["values"][0][0]) >= 40
    assert bodies_jar.dto_body(fixture_classes, "com.example.Missing") is None


def test_number_range_moves_when_the_default_does_not_fit():
    base = {"type": "number", "min": 1, "max": 100, "decimals": 2, "presence": 1.0}
    def ann(name, **values):
        return {"type": "jakarta.validation.constraints." + name, "values": values}
    assert bodies_jar.number_range(base, [ann("DecimalMax", value="0.5")])["min"] == 0.5
    assert bodies_jar.number_range(base, [ann("DecimalMin", value="0.5"), ann("DecimalMax", value="0.8")]) == \
        {**base, "min": 0.5, "max": 0.8}
    assert bodies_jar.number_range(base, [ann("Min", value=None)]) == base     # @Min llegit sense valor (long)
    contradictory = bodies_jar.number_range(base, [ann("DecimalMin", value="5"), ann("DecimalMax", value="2")])
    assert (contradictory["min"], contradictory["max"]) == (5, 5)              # el mínim que demanen


def test_email_respects_size():
    annotations = [{"type": "jakarta.validation.constraints.Email", "values": {}},
                   {"type": "jakarta.validation.constraints.Size", "values": {"max": 20}}]
    value, form = bodies_jar.text_model("contact", annotations)
    assert form == {"prefix": "storm.", "suffix": "@example.com", "max": 20}
    assert len(value) <= 20 and value.endswith("@example.com")


def test_dto_never_makes_an_id_unique():
    classes = {"X": {"name": "X", "annotations": [], "fields": [
        {"name": name, "type": "java.lang.String", "static": False, "annotations": []} for name in ("ownerId", "code")]}}
    _, unique = bodies_jar.dto_body(classes, "X", {"ownerId", "code"})
    assert list(unique) == ["code"]


def test_jar_libraries_are_skipped(tmp_path):
    """Les classes de BOOT-INF/lib/ són llibreries, no l'app."""
    import zipfile
    with zipfile.ZipFile(FIXTURE_JAR) as source:
        entry = next(name for name in source.namelist() if name.endswith("SignupForm.class"))
        data = source.read(entry)
    for folder, expected in (("BOOT-INF/lib/", {}), ("BOOT-INF/classes/", {"com.example.SignupForm"})):
        jar = tmp_path / "app.jar"
        with zipfile.ZipFile(jar, "w") as target:
            target.writestr(folder + "com/example/SignupForm.class", data)
        assert set(bodies_jar.read_classes(jar)) == set(expected)


def test_empty_log_bodies_are_built_from_the_dto():
    """Un log que desa {} (com les altes de la bankapp): amb el .jar, el body surt del DTO."""
    df = frame([{"status": 201, "body": {}}] * 3)
    endpoints = [{"method": "POST", "endpoint": "/items", "body": {"type": "com.example.SignupForm", "fields": {}}}]
    assert build_body_models(df, endpoints)["POST /items"] == {}
    model, enhancement = build_with_layer(df, endpoints, FIXTURE_JAR)
    assert list(model["POST /items"]) == SIGNUP_FIELDS
    assert set(enhancement.rules["POST /items"]["unique"]) == {"contact", "slogan", "nick"}


def test_the_dto_never_replaces_what_the_log_teaches():
    """Si el log té bodies amb camps, mana el log encara que el .jar en tingui el DTO."""
    df = frame([{"status": 200, "body": {"handle": f"h{n % 3}", "fee": n}} for n in range(10)])
    endpoints = [{"method": "POST", "endpoint": "/items", "body": {"type": "com.example.SignupForm", "fields": {}}}]
    model, _ = build_with_layer(df, endpoints, FIXTURE_JAR)
    assert model == build_body_models(df)


def test_empty_successes_and_failed_bodies_keep_the_peer_model():
    """Les 2xx porten {} i les fallades porten camps: es queda el model dels companys, no un body buit."""
    df = frame([{"status": 201, "body": {}}] * 3 + [{"status": 400, "body": {"size": 3, "note": "x"}}] * 2)
    model, _ = build_with_layer(df)
    assert model == build_body_models(df) and model["POST /items"]


# ---------------------------------------------------------------------------
# 4. El Groovy del PreProcessor, amb el Groovy de JMeter i vars/props de mentida
# ---------------------------------------------------------------------------

HARNESS = r"""
import groovy.json.JsonOutput
import groovy.json.JsonSlurper

class Vars {
    Map m = [:]
    String get(String k) { m[k] == null ? null : m[k] as String }
    void put(String k, String v) { m[k] = v }
    Object getObject(String k) { m[k] }
    void putObject(String k, Object v) { m[k] = v }
}
def vars = new Vars()
def log = new Expando()
log.error = { String message, Throwable t = null -> System.err.println("ERROR " + message) }
def input = new JsonSlurper().parse(new File(args[1]))
def script = new GroovyShell(new Binding([vars: vars, props: new Properties(), log: log])).parse(new File(args[0]).text)
def out = []
input.cases.each { c ->
    vars.putObject("stormModel", input.model)
    vars.putObject("stormIds", c.ids ?: [:])
    vars.put("stormState", c.state)
    vars.put("stormBody", c.raw != null ? c.raw : JsonOutput.toJson(c.body))
    script.run()
    out << vars.get("stormBody")
}
println JsonOutput.toJson(out)
"""

needs_groovy = pytest.mark.skipif(not list(GROOVY_LIB.glob("groovy-3*.jar")), reason="no hi ha el Groovy de JMeter")

RULES = {"POST /items": {"numbers": {"size": {"q": bodies_learn.quantile_table(list(range(1, 101))), "decimals": 2}},
                         "different": [["sourceId", "targetId"]],
                         "unique": {"contact": {"prefix": "storm.", "suffix": "@example.com"},
                                    "code": {"prefix": "storm-code-", "suffix": "", "max": 16}}}}
MODEL = {"bodies": {"POST /items": {"targetId": {"type": "choice", "values": [[1, 0.4], [2, 0.3], [3, 0.3]]}}},
         "correlation": {"body_resources": {"POST /items": {"sourceId": "/sources"}}}}


def run_groovy(tmp_path, cases, rules=RULES, model=MODEL):
    (tmp_path / "harness.groovy").write_text(HARNESS, encoding="utf-8")
    (tmp_path / "fix.groovy").write_text(bodies.script(rules), encoding="utf-8")
    (tmp_path / "input.json").write_text(json.dumps({"model": model, "cases": cases}), encoding="utf-8")
    result = subprocess.run(["java", "-cp", str(GROOVY_LIB / "*"), "groovy.ui.GroovyMain",
                             str(tmp_path / "harness.groovy"), str(tmp_path / "fix.groovy"),
                             str(tmp_path / "input.json")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return [json.loads(body) if body.startswith("{") else body for body in json.loads(result.stdout)], result.stderr


@needs_groovy
def test_groovy_different_redraws_the_free_field(tmp_path):
    cases = [{"state": "POST /items", "body": {"sourceId": 1, "targetId": 1}}] * 100
    out, _ = run_groovy(tmp_path, cases)
    assert all(b["sourceId"] == 1 and b["targetId"] in (2, 3) for b in out)


@needs_groovy
def test_groovy_different_keeps_the_correlated_field(tmp_path):
    """La correlació dels companys ha posat sourceId = 3 (un id que l'app ens ha donat): es canvia targetId."""
    cases = [{"state": "POST /items", "body": {"sourceId": 3, "targetId": 3}, "ids": {"/sources": 3}}] * 50
    out, _ = run_groovy(tmp_path, cases)
    assert all(b["sourceId"] == 3 and b["targetId"] in (1, 2) for b in out)


@needs_groovy
def test_groovy_different_keeps_the_correlated_field_when_it_is_second(tmp_path):
    """Ara és targetId el que ha fixat la correlació: s'ha de canviar sourceId."""
    model = {"bodies": {"POST /items": {"sourceId": {"type": "choice", "values": [[1, 0.5], [2, 0.5]]}}},
             "correlation": {"body_resources": {"POST /items": {"targetId": "/targets"}}}}
    cases = [{"state": "POST /items", "body": {"sourceId": 2, "targetId": 2}, "ids": {"/targets": 2}}] * 50
    out, _ = run_groovy(tmp_path, cases, model=model)
    assert all(b == {"sourceId": 1, "targetId": 2} for b in out)


@needs_groovy
def test_groovy_different_leaves_two_correlated_fields_alone(tmp_path):
    """Si la correlació ha fixat tots dos camps, el PreProcessor no en toca cap (els ha donat l'app)."""
    choices = {"type": "choice", "values": [[1, 0.5], [2, 0.5]]}     # hi hauria amb què tornar a sortejar
    model = {"bodies": {"POST /items": {"sourceId": choices, "targetId": choices}},
             "correlation": {"body_resources": {"POST /items": {"sourceId": "/sources", "targetId": "/targets"}}}}
    cases = [{"state": "POST /items", "body": {"sourceId": 2, "targetId": 2}, "ids": {"/sources": 2, "/targets": 2}}]
    out, _ = run_groovy(tmp_path, cases * 20, model=model)
    assert all(b == {"sourceId": 2, "targetId": 2} for b in out)


@needs_groovy
def test_groovy_unique_leaves_a_correlated_field_alone(tmp_path):
    rules = {"POST /items": {"numbers": {}, "different": [],
                             "unique": {"ownerRef": {"prefix": "storm-", "suffix": ""}}}}
    model = {"bodies": {}, "correlation": {"body_resources": {"POST /items": {"ownerRef": "/owners"}}}}
    cases = [{"state": "POST /items", "body": {"ownerRef": "given-by-app"}, "ids": {"/owners": "given-by-app"}},
             {"state": "POST /items", "body": {"ownerRef": "from-log"}}]
    out, _ = run_groovy(tmp_path, cases, rules=rules, model=model)
    assert out[0] == {"ownerRef": "given-by-app"}
    assert out[1]["ownerRef"].startswith("storm-") and out[1]["ownerRef"] != "from-log"


@needs_groovy
def test_groovy_unique_respects_the_length(tmp_path):
    rules = {"POST /items": {"numbers": {}, "different": [],
                             "unique": {"slogan": {"prefix": "storm-slogan-", "suffix": "", "min": 40},
                                        "nick": {"prefix": "storm-nick-", "suffix": "", "max": 8}}}}
    out, _ = run_groovy(tmp_path, [{"state": "POST /items", "body": {"slogan": "x", "nick": "y"}}] * 200, rules=rules)
    assert all(len(b["slogan"]) >= 40 for b in out) and len({b["slogan"] for b in out}) == 200
    assert all(len(b["nick"]) <= 8 for b in out) and len({b["nick"] for b in out}) == 200


@needs_groovy
def test_groovy_numbers_follow_a_skewed_shape(tmp_path):
    """90 valors entre 1 i 10 i 10 entre 900 i 1000: la mediana ha de ser petita (amb un interval pla seria ~500)."""
    values = [1 + n / 10 for n in range(90)] + [900 + n * 10 for n in range(10)]
    rules = {"POST /items": {"numbers": {"size": {"q": bodies_learn.quantile_table(values), "decimals": 2}},
                             "different": [], "unique": {}}}
    out, _ = run_groovy(tmp_path, [{"state": "POST /items", "body": {"size": 0}}] * 400, rules=rules)
    sizes = sorted(float(b["size"]) for b in out)
    assert sizes[200] < 20 and sum(s > 100 for s in sizes) < 80


@needs_groovy
def test_groovy_unique_values_never_repeat(tmp_path):
    cases = [{"state": "POST /items", "body": {"contact": "x", "code": "y"}}] * 300
    out, _ = run_groovy(tmp_path, cases)
    contacts = [b["contact"] for b in out]
    assert len(set(contacts)) == 300
    assert all(re.fullmatch(r"storm\.[0-9a-z]+-\d+@example\.com", c) for c in contacts)
    assert len({b["code"] for b in out}) == 300 and all(len(b["code"]) <= 16 for b in out)


@needs_groovy
def test_groovy_numbers_follow_the_quantiles(tmp_path):
    cases = [{"state": "POST /items", "body": {"size": 0}}] * 400
    out, _ = run_groovy(tmp_path, cases)
    sizes = [float(b["size"]) for b in out]
    assert min(sizes) >= 1 and max(sizes) <= 100
    assert all(round(s, 2) == s for s in sizes)
    assert 35 < sorted(sizes)[200] < 65      # la mediana d'1..100 és 50,5


THREADS_HARNESS = r"""
import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import java.util.concurrent.Callable
import java.util.concurrent.Executors

class Vars {
    Map m = [:]
    String get(String k) { m[k] == null ? null : m[k] as String }
    void put(String k, String v) { m[k] = v }
    Object getObject(String k) { m[k] }
    void putObject(String k, Object v) { m[k] = v }
}
def props = new Properties()            // com a JMeter: unes props per a tots els fils
def log = new Expando()
log.error = { String message, Throwable t = null -> System.err.println("ERROR " + message) }
def input = new JsonSlurper().parse(new File(args[1]))
def text = new File(args[0]).text
def modelJson = JsonOutput.toJson(input.model)
def state = input.state as String
def bodyJson = JsonOutput.toJson(input.body)
int calls = input.calls as int
def results = Collections.synchronizedList([])
def pool = Executors.newFixedThreadPool(input.threads as int)
def futures = (1..(input.threads as int)).collect {
    pool.submit({
        def vars = new Vars()          // com a JMeter: unes vars per fil, i un model per fil
        def model = new JsonSlurper().parseText(modelJson)
        def script = new GroovyShell(new Binding([vars: vars, props: props, log: log])).parse(text)
        calls.times {
            vars.putObject("stormModel", model)
            vars.put("stormState", state)
            vars.put("stormBody", bodyJson)
            script.run()
            results << vars.get("stormBody")
        }
    } as Callable)
}
futures*.get()
pool.shutdown()
println JsonOutput.toJson(results)
"""


@needs_groovy
def test_groovy_unique_values_never_repeat_across_threads(tmp_path):
    (tmp_path / "threads.groovy").write_text(THREADS_HARNESS, encoding="utf-8")
    (tmp_path / "fix.groovy").write_text(bodies.script(RULES), encoding="utf-8")
    (tmp_path / "input.json").write_text(json.dumps({"model": MODEL, "state": "POST /items", "threads": 8,
                                                     "calls": 100, "body": {"contact": "x"}}), encoding="utf-8")
    result = subprocess.run(["java", "-cp", str(GROOVY_LIB / "*"), "groovy.ui.GroovyMain",
                             str(tmp_path / "threads.groovy"), str(tmp_path / "fix.groovy"),
                             str(tmp_path / "input.json")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    contacts = [json.loads(body)["contact"] for body in json.loads(result.stdout)]
    assert len(contacts) == 800 and len(set(contacts)) == 800


@needs_groovy
def test_groovy_leaves_other_requests_and_bad_bodies_alone(tmp_path):
    cases = [{"state": "GET /other", "raw": '{"a": 1}'},
             {"state": "POST /items", "raw": ""},
             {"state": "POST /items", "raw": "no és JSON"}]
    out, stderr = run_groovy(tmp_path, cases)
    assert out == [{"a": 1}, "", "no és JSON"]
    assert "ERROR STORM-IA bodies: POST /items" in stderr


# ---------------------------------------------------------------------------
# 5. A través de python -m ai: el PreProcessor al .jmx
# ---------------------------------------------------------------------------

def embedded_json(script, marker):
    text = script.split("parseText('''", 1)[1].split("''')", 1)[0]
    return json.loads(text.replace("\\\\", "\\")) if marker else text


def test_plan_carries_the_preprocessor_first_in_the_loop(tmp_path):
    plan = generate(AI, ["--ai-bodies", "--logs", REFERENCE, "--jar", JAR, "--session"], tmp_path / "b.jmx")
    root = jmx_post.read(plan).getroot()
    loop_tree = jmx_post.child_tree(root, root.find(".//WhileController"))
    first = loop_tree[0]
    assert first.tag == "JSR223PreProcessor" and first.get("testname") == bodies.TESTNAME
    assert loop_tree[1].tag == "hashTree" and len(loop_tree[1]) == 0
    script = first.find("stringProp[@name='script']").text
    rules = embedded_json(script, True)
    assert rules["POST /api/transfers"]["different"] == [["fromAccountId", "toAccountId"]]

    # el model dels companys, dins del .jmx: les altes ja no van buides (DTO del .jar)
    model_script = root.find(".//JSR223PreProcessor[@testname='Elegir primera petición']/stringProp[@name='script']").text
    model = embedded_json(model_script, True)
    assert model["bodies"]["POST /api/users"] and model["bodies"]["POST /api/accounts"]


def test_plan_without_rules_has_no_preprocessor(tmp_path):
    """Només .jar (sense logs): no hi ha res après del log ni cap camp únic al .jar d'exemple."""
    plan = generate(AI, ["--ai-bodies", "--jar", JAR], tmp_path / "jar.jmx")
    assert bodies.TESTNAME not in plan.read_text(encoding="utf-8")


def test_bodies_check_counts_and_shows_n():
    from ai.bench import bodies_check
    df = pd.DataFrame([{"method": "POST", "endpoint": "/api/transfers", "body": {"fromAccountId": 1, "toAccountId": 1}},
                       {"method": "POST", "endpoint": "/api/transfers", "body": {"fromAccountId": 1, "toAccountId": 2}},
                       {"method": "POST", "endpoint": "/api/users", "body": {"email": "a@x.test"}},
                       {"method": "POST", "endpoint": "/api/users", "body": {"email": "a@x.test"}}])
    assert bodies_check.same_account(df) == (1, 2)
    assert bodies_check.repeated_emails(df) == (1, 2)
    none, count = bodies_check.repeated_emails(df[df["endpoint"] != "/api/users"])
    assert none != none and count == 0          # NaN: sense correus no s'ha mesurat res
    runs = [{"A": {"acceptance_body": 50.0, "repeated_emails": float("nan")},
             "B": {"acceptance_body": 90.0, "repeated_emails": 0}},
            {"A": {"acceptance_body": 60.0, "repeated_emails": float("nan")},
             "B": {"acceptance_body": 95.0}}]
    text = bodies_check.markdown(bodies_check.summarize(runs, ["A", "B"]), len(runs))
    assert text.startswith("Execucions: 2\n")
    row = next(line for line in text.splitlines() if line.startswith("| repeated_emails"))
    assert row.split("|")[2].strip() == "—" and "(n=1)" in row.split("|")[3]


# ---------------------------------------------------------------------------
# 6. Res de la bankapp dins de la capa (RUMB § 3: qualsevol app Java)
# ---------------------------------------------------------------------------

# Paraules del domini de l'app de prova (noms de recursos i de camps dels seus bodies)
APP_TERMS = re.compile(r"account|transfer|iban|deposit|withdraw|bankapp|balance|saldo|cuenta|ingreso|amount|"
                       r"concept|email|user", re.IGNORECASE)
# Excepcions exactes, que no són de l'app: l'anotació estàndard @Email de Jakarta (bodies_jar.py la llegeix de
# qualsevol app) i les seves constants, i els usuaris virtuals de JMeter (canary.py)
ALLOWED = re.compile(r'@Email\b|"Email"|\bEMAIL_(PREFIX|SUFFIX)\b|\bvusers\b|\bone_more_user\b')
LAYER = ROOT / "ai"
OUTSIDE = ("bench", "tests")


def app_terms(folder):
    """[(fitxer, línia, paraula)] de les paraules de l'app de prova al codi de la capa."""
    found = []
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if path.suffix not in (".py", ".groovy") or relative.parts[0] in OUTSIDE:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in APP_TERMS.finditer(ALLOWED.sub("", line)):
                found.append((relative.as_posix(), number, match.group()))
    return found


def test_the_layer_knows_nothing_of_the_test_app():
    assert app_terms(LAYER) == []


def test_the_search_finds_what_it_looks_for(tmp_path):
    """Prova en negatiu del test d'abans: si hi hagués una paraula de l'app, la trobaria."""
    (tmp_path / "enhancements").mkdir()
    (tmp_path / "enhancements" / "x.py").write_text("ACCOUNT = 1\n", encoding="utf-8")
    (tmp_path / "bench").mkdir()
    (tmp_path / "bench" / "y.py").write_text("account = 1\n", encoding="utf-8")
    (tmp_path / "enhancements" / "z.groovy").write_text('body.email = "x" // @Email\n', encoding="utf-8")
    assert app_terms(tmp_path) == [("enhancements/x.py", 1, "ACCOUNT"), ("enhancements/z.groovy", 1, "email")]


# ---------------------------------------------------------------------------
# 7. JMeter real (si n'hi ha): el pla amb el PreProcessor s'executa sense errors de Groovy
# ---------------------------------------------------------------------------

def synthetic_log(path, sessions=40):
    """Un log genèric on els bodies tenen les tres regles: sourceId != targetId sempre, "code" únic i
    "size" amb una forma esbiaixada (molts petits i alguns de molt grans)."""
    pairs = [(a, b) for a in (1, 2, 3) for b in (1, 2, 3) if a != b]
    lines, n = [], 0
    for s in range(sessions):
        start = pd.Timestamp("2026-01-01T10:00:00Z") + pd.Timedelta(minutes=s)
        for step in range(3):
            body = None
            if step:
                source, target = pairs[n % len(pairs)]
                size = 900 + n % 10 * 10 if n % 10 == 0 else 1 + n % 9
                body = {"sourceId": source, "targetId": target, "size": size, "code": f"ref-{n:04d}"}
                n += 1
            lines.append({"timestamp": (start + pd.Timedelta(seconds=step)).isoformat().replace("+00:00", "Z"),
                          "requestId": f"r{s}-{step}", "sessionId": f"s{s}", "userId": None,
                          "method": "POST" if step else "GET", "endpoint": "/items", "path": "/items",
                          "body": body, "status": 201 if step else 200, "durationMs": 5,
                          "requestSizeBytes": 0, "responseSizeBytes": 0})
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


@pytest.mark.skipif(not jmeter.jmeter_binary().exists(), reason="no hi ha JMeter local")
def test_real_jmeter_runs_the_preprocessor(tmp_path):
    """Sense el PreProcessor, els companys triarien sourceId i targetId per separat (coincidirien ~1/3) i
    repetirien els "code" del log: aquesta prova fallaria."""
    log = synthetic_log(tmp_path / "items.jsonl")
    plan = generate(AI, ["--ai-bodies", "--logs", str(log)], tmp_path / "b.jmx")
    port = free_port()
    received = tmp_path / "r.jsonl"
    server = subprocess.Popen([sys.executable, "-m", "ai.bench.echo_server", "--out", str(received),
                               "--port", str(port), "--logs", str(log)], cwd=ROOT,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        code, output = jmeter.run(plan, tmp_path / "r.jtl", tmp_path / "j.log",
                                  {"host": "127.0.0.1", "port": port, "duration": 12, "rampup": 1, "vusers": 6})
    finally:
        server.terminate()
        server.wait(timeout=10)
    assert code == 0, output
    errors = [line for line in (tmp_path / "j.log").read_text(encoding="utf-8").splitlines() if " ERROR " in line]
    assert errors == []
    sent = [b for b in parse_logs(str(received))["body"] if isinstance(b, dict) and "code" in b]
    assert len(sent) >= 20
    assert all(b["sourceId"] != b["targetId"] for b in sent)
    codes = [b["code"] for b in sent]
    assert len(set(codes)) == len(codes) and all(c.startswith("ref-") and not re.fullmatch(r"ref-\d{4}", c)
                                                 for c in codes)
    assert all(1 <= b["size"] <= 990 for b in sent)
