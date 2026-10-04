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
