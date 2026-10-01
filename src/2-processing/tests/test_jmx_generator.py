import xml.etree.ElementTree as ET

from jmx_generator.generator import generate_jmx

MATRIX = {
    "GET /api/users/{id}": {"GET /api/accounts/{id}": 0.95, "POST /api/transfers": 0.05},
    "GET /api/accounts/{id}": {"POST /api/accounts/{id}/deposit": 1.0},
}
PROFILE = {"vusers": 10, "ramp_up_seconds": 30, "duration_seconds": 120}


def render(tmp_path, **kwargs):
    out = tmp_path / "plan.jmx"
    generate_jmx(MATRIX, PROFILE, str(out), **kwargs)
    return ET.parse(out).getroot()


def prop(element, name):
    return element.find(f"*[@name='{name}']").text


def test_valid_xml_with_loop_controller(tmp_path):
    root = render(tmp_path)
    group = root.find(".//ThreadGroup")
    assert prop(group, "ThreadGroup.num_threads") == "10"
    assert prop(group, "ThreadGroup.duration") == "120"
    assert group.find("elementProp[@name='ThreadGroup.main_controller']") is not None


def test_samplers_keep_method_and_drop_unlikely(tmp_path):
    samplers = render(tmp_path).findall(".//HTTPSamplerProxy")
    assert [(prop(s, "HTTPSampler.method"), prop(s, "HTTPSampler.path")) for s in samplers] == [
        ("GET", "/api/accounts/${id}"),
        ("POST", "/api/accounts/${id}/deposit"),
    ]


def test_path_params_declared_and_target_configurable(tmp_path):
    root = render(tmp_path, host="bankapp", port=9090)
    assert [a.get("name") for a in root.find(".//TestPlan").iter("elementProp") if a.get("elementType") == "Argument"] == ["id"]
    defaults = root.find(".//ConfigTestElement")
    assert prop(defaults, "HTTPSampler.domain") == "${__P(host,bankapp)}"
    assert prop(defaults, "HTTPSampler.port") == "${__P(port,9090)}"
