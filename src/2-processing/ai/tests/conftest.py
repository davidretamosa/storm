"""Fixtures dels tests de la capa d'IA."""
import pytest

from ai.tests.support import INPUTS, MAIN, generate


@pytest.fixture(scope="session")
def reference_plans(tmp_path_factory):
    """El .jmx de main.py (la cadena dels companys) per a cada entrada, generat un sol cop."""
    folder = tmp_path_factory.mktemp("main")
    return {name: generate(MAIN, args, folder / f"{name}.jmx") for name, args in INPUTS.items()}
