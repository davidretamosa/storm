"""Test de contracte: la forma de la cadena dels companys sobre la qual s'han validat els embolcalls.

Si un d'aquests tests falla, el codi dels companys ha canviat: revalida els embolcalls i actualitza el lock.
"""
import inspect
import sys
from pathlib import Path

import pytest

import main
from ai import upstream
from ai.cli import run
from ai.hooks import WRAPPABLE
from ai.tests.support import INPUTS, ROOT

SIGNATURES = {
    "parse_logs": "(log_file_path)",
    "parse_jar": "(jar_path)",
    "compare_with_logs": "(endpoints, df)",
    "build_session_config": "(session_endpoint, df=None, users=None)",
    "remove_session_requests": "(df, endpoints, session_endpoint)",
    "build_markov_model": "(df=None, min_probability=0.0, max_steps=50, endpoints=None, jar_weight=1)",
    "build_think_times": "(df, samples=20, max_ms=120000)",
    "add_default_pauses": "(think_times, model, default_pause_ms=[1000, 1500, 2000, 2500, 3000])",
    "build_path_params": "(df)",
    "build_body_models": "(df, endpoints=None)",
    "predict_traffic_scale": "(df, ramp_up_seconds=60, duration_seconds=300)",
    "build_correlation": "(model, bodies)",
    "generate_jmx": "(model: dict, think_times: Dict[str, Dict[str, List[int]]], profile: Dict[str, int], "
                    "output_path: str, host: str = 'localhost', port: int = 8080, path_params: Optional[dict] = None, "
                    "bodies: Optional[dict] = None, correlation: Optional[dict] = None, "
                    "session: Optional[dict] = None) -> None",
}

TAIL = ["build_markov_model", "build_think_times", "add_default_pauses", "build_path_params",
        "build_body_models", "predict_traffic_scale", "build_correlation", "generate_jmx"]
CALL_ORDER = {
    "logs": ["parse_logs", *TAIL],
    "jar": ["parse_jar", *TAIL],
    "logs+jar": ["parse_logs", "parse_jar", "compare_with_logs", *TAIL],
    "logs+jar+session": ["parse_logs", "parse_jar", "compare_with_logs",
                         "build_session_config", "remove_session_requests", *TAIL],
    "martina+session": ["parse_logs", "build_session_config", "remove_session_requests", *TAIL],
}


def test_every_wrapped_function_is_frozen():
    assert set(SIGNATURES) == set(WRAPPABLE)


@pytest.mark.parametrize("name", WRAPPABLE)
def test_signature(name):
    assert str(inspect.signature(getattr(main, name))) == SIGNATURES[name]


@pytest.mark.parametrize("name", INPUTS)
def test_call_order_of_main(name, tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    installation = run(["--ai-noop", *INPUTS[name], "--output", str(tmp_path / "plan.jmx")])
    assert [called for called, _ in installation.calls] == CALL_ORDER[name]


def test_main_still_parses_argv_inside_main(tmp_path, monkeypatch):
    """La capa passa els arguments posant sys.argv: main.main() els ha de llegir ell mateix."""
    assert "parse_args()" in inspect.getsource(main.main)
    assert list(inspect.signature(main.main).parameters) == []


def test_storm_model_hook_in_groovy():
    """Ganxo per al model per grup (T-2): els scripts només llegeixen el model incrustat si stormModel és buit."""
    common = (ROOT / "jmx_generator/templates/markov_common.groovy").read_text(encoding="utf-8")
    assert 'def model = vars.getObject("stormModel")\nif (model == null) {' in common
    assert 'vars.putObject("stormModel", model)' in common


def test_upstream_lock_matches():
    found = upstream.problems()
    assert not found, f"{found}: {upstream.MESSAGE}"
