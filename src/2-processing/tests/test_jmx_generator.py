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
    assert prop(group, "ThreadGroup.num_threads") == "10"
    assert prop(group, "ThreadGroup.duration") == "120"
    assert group.find("elementProp[@name='ThreadGroup.main_controller']") is not None


def test_one_sampler_per_state_in_switch_order(tmp_path):
    root = render(tmp_path)
    samplers = list(root.iter("HTTPSamplerProxy"))
    # El índice del Switch es la posición en model["states"]
    assert [(s.get("testname"), prop(s, "HTTPSampler.method"), prop(s, "HTTPSampler.path")) for s in samplers] == [
        ("GET /api/accounts/{id}", "GET", "/api/accounts/${id}"),
        ("GET /api/users/{id}", "GET", "/api/users/${id}"),
        ("POST /api/accounts/{id}/deposit", "POST", "/api/accounts/${id}/deposit"),
    ]
    assert prop(root.find(".//SwitchController"), "SwitchController.value") == "${stormIndex}"


def test_markov_scripts_embed_model(tmp_path):
    root = render(tmp_path)
    while_condition = prop(root.find(".//WhileController"), "WhileController.condition")
    assert '"END"' in while_condition
    scripts = {e.tag: prop(e, "script") for e in root.iter() if e.tag.startswith("JSR223")}
    assert set(scripts) == {"JSR223PreProcessor", "JSR223Timer", "JSR223PostProcessor"}

    embedded = re.search(r"parseText\('''(.*?)'''\)", scripts["JSR223PostProcessor"], re.S).group(1)
    assert json.loads(embedded) == {**MODEL, "think_time_ms": THINK_TIMES, "path_params": PATH_PARAMS, "bodies": BODIES}
    # JMeter sustituye ${...} en los scripts: no puede aparecer ninguno
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
