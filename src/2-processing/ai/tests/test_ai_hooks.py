"""La xarxa de seguretat dels embolcalls, provada a posta."""
import sys

import pytest

import main
from ai import jmx_post, upstream
from ai import upstream as lock
from ai.cli import build_parser, run
from ai.hooks import WRAPPABLE, HookError, Installation
from ai.tests.support import INPUTS, ROOT


@pytest.fixture(autouse=True)
def in_processing(monkeypatch):
    monkeypatch.chdir(ROOT)


def test_only_ai_options_are_read():
    opts, rest = build_parser().parse_known_args(["--ai-groups", "--ai-seed", "7", "--logs", "x.log", "--port", "9"])
    assert opts.groups and opts.ai_seed == 7 and not opts.traffic
    assert rest == ["--logs", "x.log", "--port", "9"]


def test_no_abbreviations():
    """allow_abbrev=False: "--ai-t" no s'entén com --ai-traffic (va a main.py, que el rebutja)."""
    opts, rest = build_parser().parse_known_args(["--ai-t"])
    assert not opts.traffic and rest == ["--ai-t"]


def test_all_off_installs_nothing(tmp_path, monkeypatch):
    seen = {}
    real_main = main.main

    def spy():
        seen.update({name: getattr(main, name) for name in WRAPPABLE})
        real_main()

    monkeypatch.setattr(main, "main", spy)
    assert run([*INPUTS["logs"], "--output", str(tmp_path / "p.jmx")]) is None
    assert all(not getattr(function, "_storm_ai_hook", False) for function in seen.values())


def test_wrappers_are_restored(tmp_path):
    before = {name: getattr(main, name) for name in WRAPPABLE}
    run(["--ai-noop", *INPUTS["logs"], "--output", str(tmp_path / "p.jmx")])
    assert {name: getattr(main, name) for name in WRAPPABLE} == before


def test_wrappers_are_restored_after_a_failure(tmp_path):
    before = {name: getattr(main, name) for name in WRAPPABLE}
    with pytest.raises(SystemExit):
        run(["--ai-noop"])  # main.py: "hace falta --logs, --jar o los dos"
    assert {name: getattr(main, name) for name in WRAPPABLE} == before
    assert sys.argv[0] != "main.py"


@pytest.mark.parametrize("name", WRAPPABLE)
def test_missing_function_fails_hard(name, monkeypatch, tmp_path):
    monkeypatch.delattr(main, name)
    with pytest.raises(HookError, match=f"main.{name} no existeix"):
        run(["--ai-noop", *INPUTS["logs+jar+session"], "--output", str(tmp_path / "p.jmx")])


def test_uncalled_active_wrapper_fails(monkeypatch, tmp_path):
    """Si main.py deixa de passar per una funció embolcallada, la capa ho ha de dir."""
    from traffic_model.correlation import build_correlation   # l'original, sense cap embolcall
    real_main = main.main

    def main_that_skips_correlation():
        main.build_correlation = build_correlation   # com si main.py ja no passés per l'embolcall
        real_main()

    monkeypatch.setattr(main, "main", main_that_skips_correlation)
    with pytest.raises(HookError, match="build_correlation"):
        run(["--ai-noop", *INPUTS["logs"], "--output", str(tmp_path / "p.jmx")])
    assert not (tmp_path / "p.jmx").exists()   # el pla amb la capa saltada no queda al disc


def test_drifted_upstream_refuses_active_layers(monkeypatch, tmp_path):
    monkeypatch.setattr(lock, "problems", lambda: ["ha canviat: traffic_model/markov.py"])
    with pytest.raises(HookError, match="revalida els embolcalls i actualitza el lock"):
        run(["--ai-noop", *INPUTS["logs"], "--output", str(tmp_path / "p.jmx")])
    assert not (tmp_path / "p.jmx").exists()
    run([*INPUTS["logs"], "--output", str(tmp_path / "p.jmx")])   # tot desactivat: la cadena dels companys, igual
    assert (tmp_path / "p.jmx").exists()


def test_conditional_functions_are_not_required(tmp_path):
    """Amb només logs, parse_jar no es crida i no és cap error."""
    installation = run(["--ai-noop", *INPUTS["logs"], "--output", str(tmp_path / "p.jmx")])
    assert "parse_jar" not in installation.expected_calls()
    assert not installation.called("parse_jar")


def test_double_install_is_refused():
    with Installation({}):
        with pytest.raises(HookError, match="ja està embolcallada"):
            with Installation({}):
                pass


def test_canary_wrapper_is_called(tmp_path):
    installation = run(["--ai-canary", *INPUTS["logs"], "--output", str(tmp_path / "p.jmx")])
    assert installation.layers["predict_traffic_scale"] and installation.called("predict_traffic_scale")


def test_round_trip_is_canonically_identical(reference_plans, tmp_path):
    for name, plan in reference_plans.items():
        copy = tmp_path / f"{name}.jmx"
        copy.write_bytes(plan.read_bytes())
        jmx_post.post_process(copy, [])
        assert jmx_post.canonical(copy) == jmx_post.canonical(plan), name


def test_canonical_sees_a_real_change(reference_plans, tmp_path):
    """Prova en negatiu de la comparació canònica: un canvi de contingut sí que es veu."""
    plan = reference_plans["logs"]
    copy = tmp_path / "changed.jmx"
    copy.write_text(plan.read_text(encoding="utf-8").replace("Usuarios virtuales", "Usuarios virtualez"),
                    encoding="utf-8")
    assert jmx_post.canonical(copy) != jmx_post.canonical(plan)


def test_lock_detects_tampering(tmp_path):
    """Una còpia del codi dels companys amb un byte canviat, un fitxer esborrat i un de nou."""
    entries = upstream.read_lock()
    for path in entries:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes((ROOT / path).read_bytes())
    assert upstream.problems(root=tmp_path) == []

    (tmp_path / "traffic_model/markov.py").write_text("# canviat\n", encoding="utf-8")
    (tmp_path / "tools/demo_server.py").unlink()
    (tmp_path / "traffic_model/new_builder.py").write_text("", encoding="utf-8")
    found = upstream.problems(root=tmp_path)
    assert "ha canviat: traffic_model/markov.py" in found
    assert "ha desaparegut: tools/demo_server.py" in found
    assert "fitxer de codi nou: traffic_model/new_builder.py" in found
