"""Fixtures dels tests del banc."""
import pytest

from bench.tests.support import INPUTS, generate


@pytest.fixture(scope="session")
def reference_plans(tmp_path_factory):
    """El .jmx de main.py sense cap flag per a cada entrada, generat un sol cop."""
    folder = tmp_path_factory.mktemp("main")
    return {name: generate(args, folder / f"{name}.jmx") for name, args in INPUTS.items()}
