"""Bodies realistas (capa de IA, flag --realistic-bodies): las tres reglas que se aprenden del log.

Solo de las peticiones que la aplicación aceptó (2xx, traffic_model/status_filter.py). Son genéricas:
ningún nombre de campo ni de ruta de ninguna aplicación.

  - cuantiles: de cada campo numérico, 21 cuantiles de los valores vistos. Así JMeter puede sacar
               valores con la forma del log, no de un intervalo plano entre el mínimo y el máximo;
  - distinto:  dos campos id del mismo body que, si fueran independientes, coincidirían a menudo y en
               el log no coinciden nunca (p. ej. el origen y el destino de una operación);
  - único:     campos de texto que no se repiten nunca. Se aprende su forma (lo que tienen en común al
               principio y al final) para fabricar valores nuevos sin copiar ninguno del log.

Las reglas viajan en este formato (el T-3.4 las lleva al .jmx):

    {"POST /items": {"numbers":   {"size": {"q": [5.0, ..., 49.9], "decimals": 2}},
                     "different": [["sourceId", "targetId"]],
                     "unique":    {"code": {"prefix": "ref-", "suffix": ""}}}}

Funciones que usa main.py:
- learn_body_rules(tabla, bodies, dto_unique) -> {petición: reglas}
- hide_unique_values(bodies, reglas)          -> los campos que las reglas marcan únicos ya no llevan los valores del log
"""
import json
from collections import Counter

import numpy as np

from traffic_model.dto_bodies import TEXT_PREFIX, fixed_value
from traffic_model.payloads import ID_FIELD
from traffic_model.status_filter import successful_rows

# 21 puntos: 0 %, 5 %, ..., 100 %
QUANTILES = np.linspace(0, 1, 21)

# «Distinto»: coincidencias que se esperarían si los dos campos fueran independientes. Con menos,
# que no haya ninguna puede ser casualidad y no se aprende nada.
MIN_EXPECTED_MATCHES = 5

# «Único»: valores vistos como mínimo (todos diferentes) para que no sea casualidad
MIN_UNIQUE_VALUES = 20

# Prefijo de un valor único cuando los valores vistos no empiezan igual
DEFAULT_PREFIX = TEXT_PREFIX


# ---------------------------------------------------------------------------
# 1. Los bodies de cada petición
# ---------------------------------------------------------------------------

def bodies_by_request(df):
    """{"POST /items": [body, body, ...]} con los bodies que son diccionarios."""
    result = {}
    if df is None or df.empty or "body" not in df.columns:
        return result
    for (method, endpoint), group in df.dropna(subset=["body"]).groupby(["method", "endpoint"]):
        bodies = [body for body in group["body"] if isinstance(body, dict)]
        if bodies:
            result[method + " " + endpoint] = bodies
    return result


def is_number(value):
    """int o float, pero no bool (en Python True es un int)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def field_values(bodies, name):
    """Los valores del campo `name` en los bodies que lo llevan."""
    return [body[name] for body in bodies if name in body]


# ---------------------------------------------------------------------------
# 2. Cuantiles de los campos numéricos
# ---------------------------------------------------------------------------

def quantile_table(values):
    """Los 21 cuantiles de una lista de números, de menor a mayor, redondeados a 6 decimales."""
    return [round(float(q), 6) for q in np.quantile(np.array(values, dtype=float), QUANTILES)]


def numeric_quantiles(bodies, fields):
    """{campo: {"q": cuantiles, "decimals": d}} de los campos que en `fields` (el modelo) son "number".

    `d` son los decimales del modelo. Un campo "choice" (p. ej. un id) no tiene cuantiles.
    """
    result = {}
    for name, spec in fields.items():
        if spec.get("type") != "number":
            continue
        values = [value for value in field_values(bodies, name) if is_number(value)]
        if values:
            result[name] = {"q": quantile_table(values), "decimals": int(spec.get("decimals", 0))}
    return result


# ---------------------------------------------------------------------------
# 3. «Distinto»: dos campos id que no coinciden nunca
# ---------------------------------------------------------------------------

def comparable(value):
    """Valor para comparar: 1 y 1.0 son lo mismo; un texto, un objeto o una lista, por su JSON."""
    if is_number(value):
        return float(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def expected_matches(a_values, b_values):
    """Coincidencias esperadas en n parejas si los dos campos fueran independientes: n · Σ p_a(v) · p_b(v)."""
    n = len(a_values)
    if n == 0:
        return 0.0
    count_a = Counter(map(comparable, a_values))
    count_b = Counter(map(comparable, b_values))
    return n * sum((count_a[v] / n) * (count_b[v] / n) for v in count_a if v in count_b)


def different_pairs(bodies):
    """[[a, b], ...]: parejas de campos id (en el orden en que aparecen) que no coinciden nunca.

    Solo se miran los bodies que llevan los dos campos (con valor). La pareja se guarda si, siendo
    independientes, se esperarían al menos MIN_EXPECTED_MATCHES coincidencias.
    """
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
            a_values = [body[a] for body in rows]
            b_values = [body[b] for body in rows]
            observed = sum(1 for x, y in zip(a_values, b_values) if comparable(x) == comparable(y))
            if observed == 0 and expected_matches(a_values, b_values) >= MIN_EXPECTED_MATCHES:
                pairs.append([a, b])
    return pairs


# ---------------------------------------------------------------------------
# 4. «Único»: textos que no se repiten nunca, y su forma
# ---------------------------------------------------------------------------

def common_prefix(texts):
    """El principio común de todos los textos ("" si no hay)."""
    if not texts:
        return ""
    # El primero y el último en orden alfabético son los más distintos: su principio común es el de todos
    first, last = min(texts), max(texts)
    size = 0
    while size < min(len(first), len(last)) and first[size] == last[size]:
        size += 1
    return first[:size]


def text_form(texts):
    """La forma de unos textos únicos: lo que tienen en común al principio y al final.

    ["ana1@x.test", "pere7@x.test"] -> {"prefix": "storm-", "suffix": "@x.test"}
    ["ref-001", "ref-002"]          -> {"prefix": "ref-00", "suffix": ""}

    - de una dirección de correo, el sufijo es solo el dominio (desde la @);
    - si algún texto lleva @ y el sufijo no, el sufijo queda vacío;
    - JMeter interpreta ${...}: un prefijo o un sufijo que lo lleve se vacía;
    - sin prefijo común, DEFAULT_PREFIX.
    """
    prefix = common_prefix(texts)
    # El sufijo se busca en lo que queda después del prefijo, para que no se solapen
    suffix = common_prefix([text[len(prefix):][::-1] for text in texts])[::-1]
    if "@" in suffix:
        suffix = suffix[suffix.index("@"):]
    elif any("@" in text for text in texts):
        suffix = ""
    if "${" in prefix:
        prefix = ""
    if "${" in suffix:
        suffix = ""
    return {"prefix": prefix or DEFAULT_PREFIX, "suffix": suffix}


def unique_fields(bodies):
    """{campo: forma} de los campos con al menos MIN_UNIQUE_VALUES valores, todos textos no vacíos y diferentes.

    Los campos id se quedan fuera: un id lo da la aplicación (o la correlación), el plan no lo inventa.
    """
    names = []
    for body in bodies:
        for name in body:
            if not ID_FIELD.search(name) and name not in names:
                names.append(name)

    result = {}
    for name in names:
        values = field_values(bodies, name)
        if len(values) < MIN_UNIQUE_VALUES:
            continue
        if not all(isinstance(value, str) and value for value in values):
            continue
        if len(set(values)) == len(values):
            result[name] = text_form(values)
    return result


# ---------------------------------------------------------------------------
# 5. Las reglas de cada petición, y los valores únicos fuera del plan
# ---------------------------------------------------------------------------

def learn_body_rules(df, bodies, dto_unique=None):
    """{petición: {"numbers": ..., "different": ..., "unique": ...}}, aprendidas de las 2xx de `df`.

    - `bodies` es el modelo ya construido: los cuantiles solo se hacen de sus campos "number";
    - una petición solo tiene regla si alguna de las tres no está vacía;
    - `dto_unique` ({petición: {campo: forma}}, del DTO del .jar) se junta con las del log, solo para
      peticiones que están en `bodies` (si un campo ya es único en el log, se queda la forma del log);
    - al final se quita la regla entera de cualquier petición cuyo JSON lleve ${ (JMeter lo interpretaría).

    No cambia `bodies`.
    """
    rules = {}
    for request, request_bodies in bodies_by_request(successful_rows(df)).items():
        fields = bodies.get(request) or {}
        rule = {
            "numbers": numeric_quantiles(request_bodies, fields),
            "different": different_pairs(request_bodies),
            "unique": unique_fields(request_bodies),
        }
        if rule["numbers"] or rule["different"] or rule["unique"]:
            rules[request] = rule

    for request, forms in (dto_unique or {}).items():
        if request not in bodies or not forms:
            continue
        rule = rules.setdefault(request, {"numbers": {}, "different": [], "unique": {}})
        for name, form in forms.items():
            if name not in rule["unique"]:
                rule["unique"][name] = dict(form)

    for request in list(rules):
        if "${" in json.dumps(rules[request], ensure_ascii=False):
            del rules[request]
    return rules


def hide_unique_values(bodies, rules):
    """Cambia en `bodies` los valores de cada campo único por uno solo, fixed_value(forma).

    Así esos campos, en esa petición, ya no llevan al plan ningún valor del log, y el valor fijo ya
    tiene la forma buena por si el PreProcessor del T-3.4 no actúa. Se mantiene la "presence" del campo.
    Solo actúa sobre esos campos: no evita que los mismos textos lleguen al plan por otro camino, p. ej.
    otra petición que los repite (un mismo código en un alta y en una consulta), una petición sin
    ninguna 2xx con campos, un campo con algún valor vacío o null, o una regla quitada por un ${.
    El valor fijo podría coincidir por azar con uno del log (si el log ya usa la misma forma).
    """
    for request, rule in rules.items():
        fields = bodies.get(request)
        if not fields:
            continue
        for name, form in rule["unique"].items():
            if name not in fields:
                continue
            presence = fields[name].get("presence", 1.0)
            fields[name] = {"type": "choice", "values": [[fixed_value(form), 1.0]], "presence": presence}
