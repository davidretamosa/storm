"""Bodies realistes (T-3): què se n'aprèn dels logs, només de les peticions que van anar bé.

Tres regles, totes genèriques (cap nom de camp ni de ruta de cap app):
  - quantils:  per a cada camp numèric, 21 quantils dels valors vistos; JMeter en treu valors per
               interpolació (CDF inversa), en lloc d'un interval pla entre el mínim i el màxim;
  - diferent:  dos camps id del mateix body que, si fossin independents, haurien de coincidir
               sovint i al log no coincideixen mai (p. ej. l'origen i el destí d'una operació);
  - únic:      camps de text que no es repeteixen mai; se n'aprèn la forma (el que tenen en comú
               al principi i al final) per fabricar-ne de nous sense copiar cap valor del log.

Les regles viatgen al .jmx com a JSON (vegeu bodies.py i bodies_fix.groovy):

    {"POST /x": {"numbers":   {"camp": {"q": [5.0, ..., 49.9], "decimals": 2}},
                 "different": [["a", "b"]],
                 "unique":    {"camp": {"prefix": "storm.", "suffix": "@example.com"}}}}
"""
import json
from collections import Counter

import numpy as np

from traffic_model.payloads import ID_FIELD

# 21 punts: 0 %, 5 %, ..., 100 %
QUANTILES = np.linspace(0, 1, 21)

# «Diferent»: coincidències que s'esperarien si els dos camps fossin independents. Amb menys, que no
# n'hi hagi cap pot ser casualitat i no se n'aprèn res.
MIN_EXPECTED_MATCHES = 5

# «Únic»: valors vistos com a mínim (tots diferents) perquè no sigui casualitat
MIN_UNIQUE_VALUES = 20

# Forma per defecte d'un valor únic quan els valors vistos no tenen res en comú
DEFAULT_PREFIX = "storm-"


def successful(df):
    """Només les peticions que l'app va acceptar (status 2xx). Sense columna status, totes."""
    if df is None or "status" not in df.columns:
        return df
    return df[df["status"].between(200, 299)]


def bodies_by_request(df):
    """{"POST /x": [body, body, ...]} amb els bodies que són diccionaris."""
    result = {}
    if df is None or df.empty or "body" not in df.columns:
        return result
    for (method, endpoint), group in df.dropna(subset=["body"]).groupby(["method", "endpoint"]):
        bodies = [body for body in group["body"] if isinstance(body, dict)]
        if bodies:
            result[method + " " + endpoint] = bodies
    return result


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def field_values(bodies, name):
    return [body[name] for body in bodies if name in body]


def quantile_table(values):
    """Els 21 quantils d'una llista de números (de menor a major)."""
    return [round(float(q), 6) for q in np.quantile(np.array(values, dtype=float), QUANTILES)]


def numeric_quantiles(bodies, fields):
    """{camp: {"q": quantils, "decimals": d}} per als camps de `fields` que són {"type": "number"}."""
    result = {}
    for name, spec in fields.items():
        if spec.get("type") != "number":
            continue
        values = [v for v in field_values(bodies, name) if is_number(v)]
        if values:
            result[name] = {"q": quantile_table(values), "decimals": int(spec.get("decimals", 0))}
    return result


def _key(value):
    """Valor comparable: 1 i 1.0 són el mateix; un objecte es compara pel seu JSON."""
    if is_number(value):
        return float(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def expected_matches(a_values, b_values):
    """Coincidències que s'esperarien en len(a_values) parells si els dos camps fossin independents."""
    n = len(a_values)
    pa, pb = Counter(map(_key, a_values)), Counter(map(_key, b_values))
    return n * sum((pa[v] / n) * (pb[v] / n) for v in pa if v in pb)


def different_pairs(bodies):
    """Parells de camps id que al log no coincideixen mai, quan per atzar haurien de coincidir."""
    names = []
    for body in bodies:
        for name in body:
            if ID_FIELD.search(name) and name not in names:
                names.append(name)

    pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            rows = [body for body in bodies if body.get(a) is not None and body.get(b) is not None]
            if not rows:
                continue
            a_values, b_values = [row[a] for row in rows], [row[b] for row in rows]
            observed = sum(1 for x, y in zip(a_values, b_values) if _key(x) == _key(y))
            if observed == 0 and expected_matches(a_values, b_values) >= MIN_EXPECTED_MATCHES:
                pairs.append([a, b])
    return pairs


def common_prefix(texts):
    first, last = min(texts), max(texts)
    size = 0
    while size < min(len(first), len(last)) and first[size] == last[size]:
        size += 1
    return first[:size]


def text_form(texts):
    """La forma d'uns textos únics: el que tenen en comú al principi i al final.

    ["ana1@x.com", "pere7@x.com"] -> {"prefix": "storm-", "suffix": "@x.com"}
    ["ref-001", "ref-002"]        -> {"prefix": "ref-00", "suffix": ""}
    """
    prefix = common_prefix(texts)
    suffix = common_prefix([t[len(prefix):][::-1] for t in texts])[::-1]
    if "@" in suffix:
        suffix = suffix[suffix.index("@"):]     # d'una adreça, només el domini
    elif any("@" in t for t in texts):
        suffix = ""
    return {"prefix": prefix or DEFAULT_PREFIX, "suffix": suffix}


def unique_fields(bodies):
    """{camp: forma} dels camps de text amb prou valors i cap de repetit."""
    result = {}
    names = {name for body in bodies for name in body}
    for name in sorted(names):
        values = field_values(bodies, name)
        if len(values) < MIN_UNIQUE_VALUES or not all(isinstance(v, str) and v for v in values):
            continue
        if len(set(values)) == len(values):
            result[name] = text_form(values)
    return result


def learn(df, model):
    """Les regles de cada petició, apreses de les 2xx de `df`. `model` és el bodies ja construït:
    els quantils només es fan per als camps que hi són "number"."""
    rules = {}
    for request, bodies in bodies_by_request(successful(df)).items():
        fields = model.get(request) or {}
        rule = {
            "numbers": numeric_quantiles(bodies, fields),
            "different": different_pairs(bodies),
            "unique": unique_fields(bodies),
        }
        if any(rule.values()):
            rules[request] = rule
    return rules
