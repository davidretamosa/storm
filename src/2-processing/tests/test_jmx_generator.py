import json
import re
import xml.etree.ElementTree as ET

from jmx_generator.generator import generate_jmx

MODEL = {
    "states": ["GET /api/accounts/{id}", "GET /api/users/{id}", "POST /api/accounts/{id}/deposit"],
    "start": {"GET /api/users/{id}": 1.0},
    "transitions": {
        "GET /api/users/{id}": {"GET /api/accounts/{id}": 0.95, "END": 0.05},
        "GET /api/accounts/{id}": {"POST /api/accounts/{id}/deposit": 1.0},
        "POST /api/accounts/{id}/deposit": {"END": 1.0},
    },
    "max_steps": 50,
}
THINK_TIMES = {"GET /api/users/{id}": {"GET /api/accounts/{id}": [1000, 2000]}}
PROFILE = {"vusers": 10, "ramp_up_seconds": 30, "duration_seconds": 120}
PATH_PARAMS = {"GET /api/accounts/{id}": {"id": [["3", 0.7], ["4", 0.3]]}}
BODIES = {"POST /api/accounts/{id}/deposit": {"amount": {"type": "number", "min": 10, "max": 50, "decimals": 2, "presence": 1.0}}}


def render(tmp_path, **kwargs):
    out = tmp_path / "plan.jmx"
    generate_jmx(MODEL, THINK_TIMES, PROFILE, str(out), path_params=PATH_PARAMS, bodies=BODIES, **kwargs)
    return ET.parse(out).getroot()


def prop(element, name):
    return element.find(f"*[@name='{name}']").text


def test_valid_xml_with_loop_controller(tmp_path):
    root = render(tmp_path)
    group = root.find(".//ThreadGroup")
    # Se pueden cambiar al lanzar JMeter: -Jvusers=... -Jrampup=... -Jduration=...
    assert prop(group, "ThreadGroup.num_threads") == "${__P(vusers,10)}"
    assert prop(group, "ThreadGroup.ramp_time") == "${__P(rampup,30)}"
    assert prop(group, "ThreadGroup.duration") == "${__P(duration,120)}"
    assert group.find("elementProp[@name='ThreadGroup.main_controller']") is not None


def test_one_sampler_per_state_in_switch_order(tmp_path):
    root = render(tmp_path)
    samplers = list(root.iter("HTTPSamplerProxy"))
    # El índice del Switch es la posición en model["states"]
    assert [(s.get("testname"), prop(s, "HTTPSampler.method"), prop(s, "HTTPSampler.path")) for s in samplers] == [
        ("GET /api/accounts/{id}", "GET", "/api/accounts/${id}${stormQuery}"),
        ("GET /api/users/{id}", "GET", "/api/users/${id}${stormQuery}"),
        ("POST /api/accounts/{id}/deposit", "POST", "/api/accounts/${id}/deposit${stormQuery}"),
    ]
    assert prop(root.find(".//SwitchController"), "SwitchController.value") == "${stormIndex}"


def test_markov_scripts_embed_model(tmp_path):
    root = render(tmp_path)
    while_condition = prop(root.find(".//WhileController"), "WhileController.condition")
    assert '"END"' in while_condition

    scripts = {
        e.tag: prop(e, "script")
        for e in root.iter()
        if e.tag.startswith("JSR223")
    }

    assert set(scripts) == {
        "JSR223PreProcessor",
        "JSR223PostProcessor"
    }

    embedded = re.search(
        r"parseText\('''(.*?)'''\)",
        scripts["JSR223PostProcessor"],
        re.S
    ).group(1)

    assert json.loads(embedded) == {
        **MODEL,
        "think_time_ms": THINK_TIMES,
        "path_params": PATH_PARAMS,
        "query_params": {},
        "header_models": {},
        "bodies": BODIES,
        "correlation": {},
        "session": None,
    }

    # JMeter sustituye ${...} en los scripts
    assert all("${" not in script for script in scripts.values())


def test_only_requests_with_bodies_send_json(tmp_path):
    samplers = {s.get("testname"): s for s in render(tmp_path).iter("HTTPSamplerProxy")}
    deposit = samplers["POST /api/accounts/{id}/deposit"]
    assert prop(deposit, "HTTPSampler.postBodyRaw") == "true"
    assert deposit.find(".//elementProp[@elementType='HTTPArgument']/stringProp[@name='Argument.value']").text == "${stormBody}"
    assert samplers["GET /api/users/{id}"].find("boolProp[@name='HTTPSampler.postBodyRaw']") is None


def test_path_params_declared_and_target_configurable(tmp_path):
    root = render(tmp_path, host="bankapp", port=9090)
    assert [a.get("name") for a in root.find(".//TestPlan").iter("elementProp") if a.get("elementType") == "Argument"] == ["id"]
    defaults = root.find(".//ConfigTestElement")
    assert prop(defaults, "HTTPSampler.domain") == "${__P(host,bankapp)}"
    assert prop(defaults, "HTTPSampler.port") == "${__P(port,9090)}"

def test_deleted_resources_in_model(tmp_path):
    correlation = {
        "creates": {},
        "path_resources": {},
        "body_resources": {},
        "deletes": {
            "DELETE /api/accounts/{id}": {
                "resource": "/api/accounts",
                "param": "id",
            }
        },
    }

    root = render(tmp_path, correlation=correlation)

    script = prop(root.find(".//JSR223PostProcessor"), "script")

    embedded = re.search(
        r"parseText\('''(.*?)'''\)", script, re.S
    ).group(1)

    assert json.loads(embedded)["correlation"] == correlation


def test_deleted_ids_management(tmp_path):
    root = render(tmp_path)

    script = prop(root.find(".//JSR223PostProcessor"), "script")

    # Registro compartido de identificadores eliminados
    assert "stormDeletedIds" in script
    assert "ConcurrentHashMap" in script

    # Registro de eliminaciones después de cada petición
    assert "rememberDeletedId(current, prev)" in script


def test_skip_request_without_available_ids(tmp_path):
    root = render(tmp_path)

    condition = prop(
        root.find(".//WhileController"),
        "WhileController.condition"
    )

    script = prop(root.find(".//JSR223PostProcessor"), "script")

    # Control de peticiones sin identificadores disponibles
    assert "stormSkipRequest" in condition
    assert 'vars.put("stormSkipRequest", "true")' in script

def test_query_params_in_model(tmp_path):
    query_params = {
        "GET /api/accounts/{id}": [
            ["", 0.75],
            ["page=0&size=5", 0.25],
        ]
    }

    root = render(tmp_path, query_params=query_params)

    script = prop(root.find(".//JSR223PostProcessor"), "script")

    embedded = re.search(
        r"parseText\('''(.*?)'''\)", script, re.S
    ).group(1)

    assert json.loads(embedded)["query_params"] == query_params


def test_query_params_in_samplers(tmp_path):
    root = render(tmp_path)

    for sampler in root.iter("HTTPSamplerProxy"):
        assert prop(sampler, "HTTPSampler.path").endswith(
            "${stormQuery}"
        )

    script = prop(root.find(".//JSR223PostProcessor"), "script")

    assert "model.query_params" in script
    assert 'vars.put("stormQuery",' in script


def test_large_model_is_split_in_groovy_literals(tmp_path):
    """Groovy no admite literales de más de 65535 caracteres: un modelo grande va en trozos."""
    # Modelo de ~150 KB con comillas, barras y no ASCII, para que algún corte caiga en medio
    awkward = "it's \\ \"q\" ''' ñ€ " * 20
    big_bodies = {
        f"POST /api/x{i}": {"f": {"type": "enum", "values": [[awkward + str(i), 1.0]], "presence": 1.0}}
        for i in range(400)
    }
    out = tmp_path / "plan.jmx"
    generate_jmx(MODEL, THINK_TIMES, PROFILE, str(out), path_params=PATH_PARAMS, bodies=big_bodies)
    root = ET.parse(out).getroot()
    script = prop(root.find(".//JSR223PostProcessor"), "script")

    m = re.search(r"parseText\(\[(.*?)\]\.join\(''\)\)", script, re.S)
    assert m, "un modelo grande debe ir como lista de trozos unidos"
    pieces = re.findall(r"'''(.*?)'''", m.group(1), re.S)
    assert len(pieces) > 1
    # Ningún literal se acerca al límite de Groovy (65535 bytes en UTF-8)
    assert all(len(p.encode("utf-8")) < 65535 for p in pieces)

    # Deshacer los escapes como lo haría Groovy y comprobar que sale el mismo modelo
    def unescape(p):
        return re.sub(r"\\(.)", r"\1", p, flags=re.S)

    assert json.loads("".join(unescape(p) for p in pieces))["bodies"] == big_bodies