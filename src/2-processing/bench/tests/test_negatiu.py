"""Prova en negatiu (RUMB § 4.1): sense cap flag, el .jmx de main.py és byte a byte el de la base.

Els 5 hashos es van mesurar sobre f4a299f (la reforma de la Maria, base de feature/processing-ia2), dues
vegades en processos separats (van coincidir), amb PYTHONHASHSEED=0, en un entorn virtual nou fet amb
src/2-processing/requirements.txt (+ scipy, que només fa servir el banc), el 2026-11-17. Si un hash canvia,
o alguna cosa ha tocat la cadena amb els flags apagats, o l'entorn no és el mateix: mira MEASURED_WITH.
"""
import importlib.metadata
import platform

import pytest

from bench.tests.support import INPUTS, generate, sha256

# On es van mesurar els hashos
MEASURED_WITH = {"python": "3.15.1", "numpy": "2.5.5", "pandas": "3.1.1", "scipy": "1.18.1", "jinja2": "3.1.6"}

EXPECTED = {
    "logs": "b37cdb5251e2274c74fb38398c01aed1971353e6fcc41d959ab243b0ffc4b769",
    "jar": "6d20f1afbe9f4a970a78702b047c88fc82dfaf7cbc6a98d44c599d734ce95853",
    "logs+jar": "b8ec350eb6ccbf0ede1116e9332af38d715c08db268ed053717fee3332968e4e",
    "logs+jar+session": "c49dd6ff79d6af3dcafa39fe7940e571c1245207de2bc35bddb358647a0b51e8",
    "bankapp+session": "bc455ae7a2a6ab7f6d526bcd9efdaa753796cac39c21512faa533208355f37ee",
}


def current_versions():
    versions = {"python": platform.python_version()}
    for package in ("numpy", "pandas", "scipy", "jinja2"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def test_the_five_inputs_are_the_ones_measured():
    assert set(INPUTS) == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_plan_without_flags_is_byte_identical(name, tmp_path):
    plan = generate(INPUTS[name], tmp_path / f"{name}.jmx")
    assert sha256(plan) == EXPECTED[name], (
        f"el .jmx de main.py {' '.join(INPUTS[name])} ha canviat; "
        f"mesurat amb {MEASURED_WITH}, ara {current_versions()}")
