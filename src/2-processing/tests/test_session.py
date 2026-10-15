"""Inicio de sesión (apps que piden X-Session-Id, como la del banco)."""
import xml.etree.ElementTree as ET

import pandas as pd

from jmx_generator.generator import generate_jmx
from traffic_model.session import build_session_config, is_session_request, remove_session_requests


def test_session_requests_are_removed_from_the_model():
    df = pd.DataFrame({"endpoint": ["/api/sessions", "/api/users/{id}", "/api/sessions/{id}"]})
    endpoints = [{"endpoint": "/api/sessions"}, {"endpoint": "/api/accounts"}]
    df, endpoints = remove_session_requests(df, endpoints, "/api/sessions")
    assert list(df["endpoint"]) == ["/api/users/{id}"]
    assert endpoints == [{"endpoint": "/api/accounts"}]
    assert not is_session_request("/api/sessionsx", "/api/sessions")


def test_users_to_log_in_with():
    assert build_session_config("/api/sessions", users=[1, 2])["users"] == [[1, 0.5], [2, 0.5]]
    df = pd.DataFrame({"user_id": [3, 3, None]})
    assert build_session_config("/api/sessions", df)["users"] == [[3, 1.0]]
    assert build_session_config("/api/sessions")["users"] == [[1, 1.0]]


def test_plan_logs_in_only_when_asked(tmp_path):
    model = {"states": ["GET /api/users/{id}"], "start": {"GET /api/users/{id}": 1.0},
             "transitions": {"GET /api/users/{id}": {"END": 1.0}}, "max_steps": 50}
    profile = {"vusers": 1, "ramp_up_seconds": 1, "duration_seconds": 1}

    without = tmp_path / "sin.jmx"
    generate_jmx(model, {}, profile, str(without))
    assert "Iniciar sesión" not in without.read_text(encoding="utf-8")

    with_session = tmp_path / "con.jmx"
    generate_jmx(model, {}, profile, str(with_session), session=build_session_config("/api/sessions", users=[1]))
    root = ET.parse(with_session).getroot()
    login = root.find(".//HTTPSamplerProxy[@testname='Iniciar sesión']")
    assert login.find("stringProp[@name='HTTPSampler.path']").text == "/api/sessions"
    headers = [h.find("stringProp[@name='Header.name']").text for h in root.iter("elementProp") if h.get("elementType") == "Header"]
    assert "X-Session-Id" in headers
