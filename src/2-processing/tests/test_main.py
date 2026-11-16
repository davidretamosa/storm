"""main.py de principio a fin con los datos de prueba (las 3 formas de usarlo)."""
import sys
import xml.etree.ElementTree as ET

import pytest

import main

LOG = "samples/access_sample.log"
JAR = "samples/demo-bankapp.jar"


@pytest.mark.parametrize("inputs", [["--logs", LOG], ["--jar", JAR], ["--logs", LOG, "--jar", JAR]])
def test_main_generates_a_valid_plan(tmp_path, monkeypatch, inputs):
    output = tmp_path / "plan.jmx"
    monkeypatch.setattr(sys, "argv", ["main.py", *inputs, "--output", str(output)])
    main.main()
    assert ET.parse(output).getroot().find(".//ThreadGroup") is not None


def test_main_needs_logs_or_jar(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py"])
    with pytest.raises(SystemExit):
        main.main()


def test_main_with_session_login(tmp_path, monkeypatch):
    output = tmp_path / "plan.jmx"
    monkeypatch.setattr(sys, "argv", ["main.py", "--logs", LOG, "--jar", JAR, "--session", "--session-users", "1,2,3",
                                      "--output", str(output)])
    main.main()
    assert "Iniciar sesión" in output.read_text(encoding="utf-8")

def test_main_with_request_headers(tmp_path, monkeypatch):
    import json
    import re
    import sys
    import xml.etree.ElementTree as ET

    import pandas as pd

    df = pd.DataFrame([
        {
            "method": "GET",
            "endpoint": "/api/products",
            "headers": {"x-test-group": ["A"]},
        },
        {
            "method": "GET",
            "endpoint": "/api/products",
            "headers": {"x-test-group": ["B"]},
        },
    ])

    # Modelo esperado de cabeceras
    expected = {
        "GET /api/products": [
            [{"x-test-group": ["A"]}, 0.5],
            [{"x-test-group": ["B"]}, 0.5],
        ]
    }

    output = tmp_path / "headers.jmx"

    from jmx_generator.generator import generate_jmx
    from traffic_model.headers import build_header_models

    header_models = build_header_models(
        df, ["x-test-group"]
    )

    assert header_models == expected

    model = {
        "states": ["GET /api/products"],
        "start": {"GET /api/products": 1.0},
        "transitions": {
            "GET /api/products": {"END": 1.0}
        },
        "status_transitions": {},
        "max_steps": 50,
    }

    profile = {
        "vusers": 1,
        "ramp_up_seconds": 1,
        "duration_seconds": 60,
    }

    generate_jmx(
        model,
        {},
        profile,
        str(output),
        header_models=header_models,
    )

    root = ET.parse(output).getroot()

    # Comprobar el modelo incrustado en los scripts
    for element in root.iter("stringProp"):
        if element.get("name") != "script":
            continue

        match = re.search(
            r"parseText\('''(.*?)'''\)",
            element.text or "",
            re.S,
        )

        if match:
            embedded = json.loads(match.group(1))
            assert embedded["header_models"] == expected
            break
    else:
        raise AssertionError("No se encontró el modelo")

    # Comprobar el preprocesador de cabeceras
    processors = root.findall(".//JSR223PreProcessor")

    assert any(
        p.get("testname") == "Preparar cabeceras HTTP"
        for p in processors
    )

def test_main_passes_headers_to_jmx(tmp_path, monkeypatch):
    import json
    import re
    import sys
    import xml.etree.ElementTree as ET
    import main

    logs = tmp_path / "headers.jsonl"
    output = tmp_path / "headers.jmx"

    attributes = [
        {
            "key": "http.request.method",
            "value": {"stringValue": "GET"}
        },
        {
            "key": "http.route",
            "value": {"stringValue": "/api/products"}
        },
        {
            "key": "http.response.status_code",
            "value": {"intValue": "200"}
        },
        {
            "key": "http.request.header.x-test-group",
            "value": {
                "arrayValue": {
                    "values": [{"stringValue": "A"}]
                }
            }
        }
    ]

    span = {
        "name": "GET /api/products",
        "kind": 2,
        "startTimeUnixNano": "1000000000",
        "endTimeUnixNano": "1010000000",
        "attributes": attributes
    }

    record = {
        "resourceSpans": [
            {
                "resource": {"attributes": []},
                "scopeSpans": [{"spans": [span]}]
            }
        ]
    }

    logs.write_text(
        json.dumps(record) + "\n",
        encoding="utf-8"
    )

    monkeypatch.setattr(sys, "argv", [
        "main.py",
        "--logs", str(logs),
        "--allowed-headers", "x-test-group",
        "--output", str(output),
    ])

    main.main()

    assert output.exists()

    root = ET.parse(output).getroot()

    for element in root.iter("stringProp"):
        if element.get("name") != "script":
            continue

        match = re.search(
            r"parseText\('''(.*?)'''\)",
            element.text or "",
            re.S,
        )

        if match:
            embedded = json.loads(match.group(1))

            assert embedded["header_models"] == {
                "GET /api/products": [
                    [{"x-test-group": ["A"]}, 1.0]
                ]
            }

            break
    else:
        raise AssertionError("No se encontró el modelo")