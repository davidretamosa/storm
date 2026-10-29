"""Bodies realistes (T-3, `--ai-bodies`): que les peticions portin valors que l'app accepta.

Dues parts:
  - capa sobre build_body_models (traffic_model/payloads.py):
      1. el model surt només de les peticions 2xx (si una petició només té bodies fallats, es queda
         el model dels companys, perquè no canviï quines peticions porten body);
      2. les peticions sense cap body al log ({} o cap), si el .jar en té el DTO, el treuen del DTO
         amb les seves validacions (bodies_jar.py);
      3. s'aprenen les regles (bodies_learn.py): quantils, «diferent» i «únic»;
  - al .jmx, un JSR223 PreProcessor (bodies_fix.groovy) que aplica les regles a cada body just
    abans d'enviar-lo, sense tocar la plantilla buildBody dels companys.

Per trobar els DTO cal el camí del .jar: una capa sobre parse_jar l'apunta (sense canviar-ne res).
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ai import jmx_post
from ai.enhancements import bodies_jar, bodies_learn
from ai.enhancements.base import Enhancement as Base

SCRIPT = Path(__file__).with_name("bodies_fix.groovy")
PLACEHOLDER = "__AI_BODIES_JSON__"
TESTNAME = "STORM-IA: corregir el body"


class Enhancement(Base):
    name = "bodies"
    flag = "--ai-bodies"
    phase = "T-3"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.jar_path = None
        self.rules = {}

    def wraps(self):
        return {"parse_jar": self.remember_jar, "build_body_models": self.build_body_models}

    def remember_jar(self, original, jar_path):
        self.jar_path = jar_path
        return original(jar_path)

    def build_body_models(self, original, df, endpoints=None):
        every = original(df, endpoints)
        good = original(bodies_learn.successful(df), endpoints)
        # Peticions amb algun body 2xx que porta camps (si les 2xx només porten {}, mana el model dels companys)
        with_good_bodies = {request for request, found in
                            bodies_learn.bodies_by_request(bodies_learn.successful(df)).items() if any(found)}
        model = {request: good[request] if request in with_good_bodies else fields
                 for request, fields in every.items()}

        unique_from_jar = self.fill_from_dto(model, df, endpoints)
        self.rules = bodies_learn.learn(df, model)
        for request, forms in unique_from_jar.items():
            rule = self.rules.setdefault(request, {"numbers": {}, "different": [], "unique": {}})
            rule["unique"].update(forms)
        hide_unique_values(model, self.rules)
        self.ctx.shared[self.name] = {"rules": self.rules}
        return model

    def fill_from_dto(self, model, df, endpoints):
        """Les peticions que el log no ensenya mai amb cap camp, des del seu DTO. Torna els camps únics."""
        if not endpoints or not self.jar_path:
            return {}
        seen = {request for request, bodies in bodies_learn.bodies_by_request(df).items() if any(bodies)}
        classes = bodies_jar.read_classes(self.jar_path)
        unique = bodies_jar.unique_names(classes)
        forms = {}
        for endpoint in endpoints:
            request = endpoint["method"] + " " + endpoint["endpoint"]
            if request not in model or request in seen or not endpoint["body"]:
                continue
            built = bodies_jar.dto_body(classes, endpoint["body"]["type"], unique)
            if built and built[0]:
                model[request], forms_here = built
                if forms_here:
                    forms[request] = forms_here
        return forms

    def edit_jmx(self, root):
        if not self.rules:
            return
        loop = root.find(".//WhileController")
        children = jmx_post.child_tree(root, loop)
        children.insert(0, preprocessor(script(self.rules)))
        children.insert(1, ET.Element("hashTree"))


def hide_unique_values(model, rules):
    """Els camps únics no porten cap valor del log al .jmx: el PreProcessor els fabrica tots.
    El valor fix que queda (prefix + "storm" + sufix) ja té la forma bona, per si el PreProcessor no actua."""
    for request, rule in rules.items():
        for name, form in rule["unique"].items():
            spec = model.get(request, {}).get(name)
            if spec:
                value = form["prefix"] + "storm" + form["suffix"]
                model[request][name] = {"type": "choice", "values": [[value, 1.0]],
                                        "presence": spec.get("presence", 1.0)}


def script(rules):
    """El Groovy amb les regles incrustades dins d'un '''...''' (mateix escapament que generator._groovy)."""
    embedded = json.dumps(rules, ensure_ascii=False).replace("\\", "\\\\").replace("'''", "\\'\\'\\'")
    return SCRIPT.read_text(encoding="utf-8").replace(PLACEHOLDER, embedded)


def preprocessor(code):
    element = ET.Element("JSR223PreProcessor", {"guiclass": "TestBeanGUI", "testclass": "JSR223PreProcessor",
                                                "testname": TESTNAME})
    for name, value in (("scriptLanguage", "groovy"), ("parameters", ""), ("filename", ""),
                        ("cacheKey", "true"), ("script", code)):
        element.append(jmx_post.string_prop(name, value))
    return element
