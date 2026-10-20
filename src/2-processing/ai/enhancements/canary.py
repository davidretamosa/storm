"""Canari: un canvi petit i conegut per comprovar que la xarxa d'embolcalls i el post-procés actuen.

- Capa sobre predict_traffic_scale: un usuari virtual més (vusers + 1).
- Post-procés: un comentari al TestPlan (TestPlan.comments, element estàndard).

Res més del .jmx no ha de canviar (ai/tests/test_ai_identity.py ho comprova).
"""
from ai import jmx_post
from ai.enhancements.base import Enhancement as Base

COMMENT = "STORM-IA canari: vusers + 1"


class Enhancement(Base):
    name = "canary"
    flag = "--ai-canary"

    def wraps(self):
        def one_more_user(original, *args, **kwargs):
            profile = original(*args, **kwargs)
            return {**profile, "vusers": profile["vusers"] + 1}
        return {"predict_traffic_scale": one_more_user}

    def edit_jmx(self, root):
        plan = root.find("./hashTree/TestPlan")
        plan.append(jmx_post.string_prop("TestPlan.comments", COMMENT))
