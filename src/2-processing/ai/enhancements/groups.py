"""Grups de visita (--ai-groups, T-2): un model de Markov per a cada tipus de visita del log.

La cadena dels companys fa un sol model per a totes les sessions, el de «la visita mitjana». Aquesta millora:
1. agrupa les sessions del log (groups_cluster.find_groups);
2. per a cada grup, torna a cridar les mateixes funcions dels companys (build_markov_model, build_think_times
   i add_default_pauses) només amb les sessions del grup;
3. afegeix al .jmx un JSR223PreProcessor (groups_pick.groovy) que, a l'inici de cada sessió, tria un grup
   segons el seu pes i en posa el model a stormModel.

El model global no canvia: és el que queda incrustat als scripts dels companys. D'ell surten els estats
(el Switch del pla és únic), els bodies, els paràmetres de ruta, la correlació i la sessió. Cada grup només
hi posa el seu inici, les seves transicions i les seves pauses.

Si només surt un grup (o no hi ha logs), la millora no fa res i ho diu.
"""
import inspect
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ai import jmx_post
from ai.enhancements.base import Enhancement as Base
from ai.enhancements.groups_cluster import find_groups
from ai.hooks import HookError

PICK_SCRIPT = Path(__file__).with_name("groups_pick.groovy")
SESSION_START = "Elegir primera petición"   # el JSR223PreProcessor dels companys que comença cada sessió
NAME = "STORM-IA: triar grup de visita"
EMBEDDED = ("parseText('''", "''')")       # on va el model incrustat als scripts (generator._groovy)
# Groovy no admet literals de més de 65.535 unitats (i la JVM, de més de 65.535 bytes): el JSON va a trossos
# de CHUNK caràcters, que fins i tot amb 6 bytes per caràcter hi caben
CHUNK = 10_000


class Enhancement(Base):
    name = "groups"
    flag = "--ai-groups"
    phase = "T-2"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.members = None      # [sessions de cada grup], o None si no hi ha grups
        self.models = []         # el model de Markov de cada grup
        self.think_times = []    # les pauses de cada grup

    def wraps(self):
        return {"build_markov_model": self.markov, "build_think_times": self.think,
                "add_default_pauses": self.pauses}

    def markov(self, original, *args, **kwargs):
        """El model global tal qual; de passada, troba els grups i en fa un model per a cadascun."""
        model = original(*args, **kwargs)
        call = _bind(original, args, kwargs)
        df = call.arguments["df"]
        if df is None or df.empty:
            _say("no hi ha logs: sense grups, el pla queda com sense la millora")
            return model

        chain = {name: call.arguments[name] for name in ("min_probability", "endpoints", "jar_weight")}
        groups, report = find_groups(df, self.ctx.seed, chain)
        self.ctx.shared["groups"] = report
        count = max(groups.values()) + 1
        if count == 1:
            _say(f"un sol grup ({report['one_group']}): el pla queda com sense la millora")
            return model

        self.members = [{s for s, g in groups.items() if g == group} for group in range(count)]
        states = set(model["states"])
        for members in self.members:
            group_model = original(*_with(call, df=df[df["session_id"].isin(members)]))
            # Amb les funcions dels companys tal qual, un subconjunt de sessions no pot donar estats nous; una capa
            # d'una altra millora per sota sí que podria, i llavors el Switch del pla no els trobaria
            if not set(group_model["states"]) <= states or not set(group_model["transitions"]) <= states:
                raise HookError("un grup té estats que no són al model global: el Switch del pla no els trobaria")
            self.models.append(group_model)
        _say(f"{count} grups de visita, de {report['sizes']} sessions")
        return model

    def think(self, original, *args, **kwargs):
        """Les pauses globals tal qual, i les de cada grup amb les seves sessions."""
        think_times = original(*args, **kwargs)
        if self.members is not None:
            call = _bind(original, args, kwargs)
            df = call.arguments["df"]
            self.think_times = [original(*_with(call, df=df[df["session_id"].isin(members)]))
                                for members in self.members]
        return think_times

    def pauses(self, original, *args, **kwargs):
        """La pausa per defecte als que no en tenen: al global i a cada grup, amb el seu model."""
        think_times = original(*args, **kwargs)
        if self.members is not None:
            call = _bind(original, args, kwargs)
            self.think_times = [original(*_with(call, think_times=group_times, model=group_model))
                                for group_times, group_model in zip(self.think_times, self.models)]
        return think_times

    def edit_jmx(self, root):
        if self.members is None:
            return
        starts = [e for e in root.iter("JSR223PreProcessor") if e.get("testname") == SESSION_START]
        if len(starts) != 1:
            raise HookError(f"el pla hauria de tenir un sol «{SESSION_START}» i en té {len(starts)}")
        start = starts[0]
        parent = jmx_post.parent_of(root, start)
        base = json.loads(unescape(embedded_model(start.find("stringProp[@name='script']").text)))

        total = sum(len(members) for members in self.members)
        data = {
            "weights": [len(members) / total for members in self.members],
            "groups": [{"start": m["start"], "transitions": m["transitions"], "think_time_ms": t}
                       for m, t in zip(self.models, self.think_times)],
        }
        head, rest = PICK_SCRIPT.read_text(encoding="utf-8").split("__BASE_MODEL_JSON__")
        middle, tail = rest.split("__GROUPS_JSON__")
        script = head + groovy_text(_json(base)) + middle + groovy_text(_json(data)) + tail

        element = ET.Element("JSR223PreProcessor", {"guiclass": "TestBeanGUI", "testclass": "JSR223PreProcessor",
                                                     "testname": NAME})
        for name, value in [("scriptLanguage", "groovy"), ("parameters", ""), ("filename", ""),
                            ("cacheKey", "true"), ("script", script)]:
            element.append(jmx_post.string_prop(name, value))
        index = list(parent).index(start)          # just abans del dels companys: és el primer
        parent.insert(index, element)
        parent.insert(index + 1, ET.Element("hashTree"))


def embedded_model(script):
    """El model incrustat en un script dels companys, tal com hi és (ja escapat per a '''...''')."""
    opening, closing = EMBEDDED
    if opening not in script:
        raise HookError("el script d'inici de sessió ja no porta el model incrustat: revalida el T-2")
    begin = script.index(opening) + len(opening)
    return script[begin:script.index(closing, begin)]


def unescape(literal):
    """El text d'un literal '''...''' de Groovy: cada barra fa que el caràcter següent valgui tal qual
    (jmx_generator/generator.py només hi escapa barres i cometes)."""
    text, i = [], 0
    while i < len(literal):
        if literal[i] == "\\" and i + 1 < len(literal):
            i += 1
        text.append(literal[i])
        i += 1
    return "".join(text)


def groovy_text(text):
    """Una expressió de Groovy que val `text`: ['''tros''', '''tros''', ...].join(), amb les barres i totes
    les cometes escapades (cap tros no pot tancar el literal, ni partir un escapament)."""
    pieces = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
    quoted = ["'''" + piece.replace("\\", "\\\\").replace("'", "\\'") + "'''" for piece in pieces]
    return "[" + ", ".join(quoted) + "].join()"


def _json(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _bind(function, args, kwargs):
    call = inspect.signature(function).bind(*args, **kwargs)
    call.apply_defaults()
    return call


def _with(call, **changes):
    """Els arguments d'una crida amb alguns canviats, en ordre de posició."""
    arguments = {**call.arguments, **changes}
    return [arguments[name] for name in call.signature.parameters]


def _say(message):
    print(f"[ai] --ai-groups: {message}", file=sys.stderr)
