"""La prova en negatiu (D-2, Addenda 1) i el control positiu de la xarxa."""
import xml.etree.ElementTree as ET

import pytest

from ai import jmx_post
from ai.enhancements import ENHANCEMENTS
from ai.enhancements.base import Enhancement, Placeholder
from ai.enhancements.canary import COMMENT
from ai.tests.support import AI, INPUTS, generate, sha256


def placeholder_flags(enhancements):
    """Les opcions de les millores que encara són buides. Quan un taller omple la seva, en surt sola."""
    return [cls.flag for cls in enhancements.values() if issubclass(cls, Placeholder)]


@pytest.mark.parametrize("name", INPUTS)
def test_all_off_is_byte_identical_to_main(name, reference_plans, tmp_path):
    plan = generate(AI, INPUTS[name], tmp_path / "ai.jmx")
    assert sha256(plan) == sha256(reference_plans[name])


@pytest.mark.parametrize("name", INPUTS)
def test_noop_wrappers_are_byte_identical(name, reference_plans, tmp_path):
    plan = generate(AI, ["--ai-noop", *INPUTS[name]], tmp_path / "noop.jmx")
    assert sha256(plan) == sha256(reference_plans[name])


@pytest.mark.parametrize("flag", placeholder_flags(ENHANCEMENTS))
def test_placeholders_only_reserialize(flag, reference_plans, tmp_path):
    """Les millores encara buides fan passar el .jmx pel post-procés: la forma pot canviar, el contingut no."""
    plan = generate(AI, [flag, *INPUTS["logs+jar+session"]], tmp_path / "placeholder.jmx")
    assert jmx_post.canonical(plan) == jmx_post.canonical(reference_plans["logs+jar+session"])


def test_a_filled_enhancement_leaves_the_placeholder_list():
    """Control positiu: una millora que ja no és Placeholder deixa de comprovar-se sense editar la llista."""
    class Filled(Enhancement):
        flag = "--ai-filled"

    class Empty(Placeholder):
        flag = "--ai-empty"

    assert placeholder_flags({"filled": Filled, "empty": Empty}) == ["--ai-empty"]


@pytest.mark.parametrize("name", INPUTS)
def test_canary_changes_only_what_it_touches(name, reference_plans, tmp_path):
    plan = generate(AI, ["--ai-canary", *INPUTS[name]], tmp_path / "canary.jmx")
    assert sha256(plan) != sha256(reference_plans[name])

    root = jmx_post.read(plan).getroot()
    reference = jmx_post.read(reference_plans[name]).getroot()
    # 1) el nombre d'usuaris virtuals per defecte, +1
    threads = root.find(".//ThreadGroup/stringProp[@name='ThreadGroup.num_threads']")
    original = reference.find(".//ThreadGroup/stringProp[@name='ThreadGroup.num_threads']").text
    vusers = int(original.split("${__P(vusers,")[1].rstrip(")}"))
    assert threads.text == f"${{__P(vusers,{vusers + 1})}}"
    # 2) el comentari del TestPlan
    test_plan = root.find("./hashTree/TestPlan")
    comments = test_plan.findall("stringProp[@name='TestPlan.comments']")
    assert [c.text for c in comments] == [COMMENT]
    # 3) i res més: desfent aquests dos canvis, el contingut és el de main.py
    threads.text = original
    test_plan.remove(comments[0])
    assert jmx_post.canonical(ET.tostring(root, encoding="unicode")) == jmx_post.canonical(reference_plans[name])
