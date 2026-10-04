"""Datos de cada petición: los valores de los {id} de la ruta y los bodies JSON.

Todo se guarda como "distribuciones": listas [valor, probabilidad]. JMeter elige un valor
al azar con esas probabilidades, así las peticiones se parecen a las reales sin repetirse.

Funciones que usa main.py:
- build_path_params(tabla)            -> valores de los {id}        (sección 2)
- build_body_models(tabla, endpoints) -> cómo es cada body          (secciones 3 y 4)
"""
import json
import re
from collections import Counter
from decimal import Decimal

# Un {parámetro} dentro de una ruta: en "/api/accounts/{id}" encuentra "id"
PATH_PARAM = re.compile(r"\{(\w+)\}")

# Campos que son identificadores: "id", "userId", "fromAccountId", "account_id"...
# Se toman de los valores vistos (no de un rango) para no inventar ids que no existen.
ID_FIELD = re.compile(r"(^id$|Id$|_id$)")

# Como mucho se guardan los 50 valores más frecuentes de cada campo
MAX_VALUES = 50


# ---------------------------------------------------------------------------
# 1. Herramienta común: de una lista de valores a [valor, probabilidad]
# ---------------------------------------------------------------------------

def distribution(values):
    """["3", "4", "3"] -> [["3", 0.67], ["4", 0.33]] (los MAX_VALUES más frecuentes)."""
    counts = Counter()
    for value in values:
        # Se cuenta su versión en texto JSON, para poder contar también objetos y listas
        key = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if "${" in key:
            continue  # JMeter interpreta ${...}: estos valores no se pueden meter en el plan
        counts[key] += 1

    top = counts.most_common(MAX_VALUES)
    total = sum(count for _, count in top)

    result = []
    for key, count in top:
        result.append([json.loads(key), count / total])
    return result


# ---------------------------------------------------------------------------
# 2. {id} de las rutas: /api/accounts/{id} -> qué números se usan
# ---------------------------------------------------------------------------

def path_regex(endpoint):
    """'/api/accounts/{id}/deposit' -> patrón que en '/api/accounts/3/deposit' captura id = 3."""
    pattern = ""
    for part in re.split(r"(\{\w+\})", endpoint):   # ["/api/accounts/", "{id}", "/deposit"]
        if PATH_PARAM.fullmatch(part):
            name = part[1:-1]                        # "{id}" -> "id"
            pattern += f"(?P<{name}>[^/]+)"          # cualquier texto sin "/", con nombre "id"
        else:
            pattern += re.escape(part)               # texto fijo, tal cual
    return re.compile("^" + pattern + "$")


def build_path_params(df):
    """Por cada petición con {parámetros}, los valores vistos en la columna 'path' y su frecuencia:

    {"GET /api/accounts/{id}": {"id": [["3", 0.4], ["1", 0.3], ...]}, ...}

    Sin logs devuelve {}: JMeter usará 1.
    """
    result = {}
    if df is None or df.empty:
        return result

    for (method, endpoint), group in df.groupby(["method", "endpoint"]):
        params = PATH_PARAM.findall(endpoint)        # "/api/accounts/{id}" -> ["id"]
        if not params:
            continue                                 # ruta sin {parámetros}: nada que hacer

        # Sacamos el valor de cada parámetro de cada ruta concreta del log
        regex = path_regex(endpoint)
        values = {}
        for name in params:
            values[name] = []
        for path in group["path"].dropna():          # "/api/accounts/3", "/api/accounts/4"...
            match = regex.match(path)
            if match:
                for name in params:
                    values[name].append(match[name])  # "3", "4"...

        request = method + " " + endpoint
        result[request] = {}
        for name in params:
            result[request][name] = distribution(values[name])
    return result


# ---------------------------------------------------------------------------
# 3. Bodies desde los logs: cómo es cada campo
# ---------------------------------------------------------------------------

def build_body_models(df, endpoints=None):
    """Cómo es el body de cada petición, campo a campo:

    {"POST /api/transfers": {"amount":  {"type": "number", "min": 5.2, "max": 250.0, "decimals": 2, "presence": 1.0},
                             "concept": {"type": "choice", "values": [["luz", 0.5], ...], "presence": 1.0}}}

    - number:   un valor al azar entre el mínimo y el máximo vistos (importes, cantidades).
    - choice:   uno de los valores vistos, según su frecuencia (textos, ids, objetos).
    - presence: en qué proporción de bodies aparece el campo (1.0 = en todos).

    Si se pasa el .jar (endpoints), las peticiones SIN ningún body en los logs lo generan
    desde su DTO (sección 4). Si hay bodies en los logs, mandan los logs.
    """
    result = models_from_logs(df)
    if endpoints:
        add_bodies_from_dto(result, endpoints)
    return result


def models_from_logs(df):
    """Modelo de cada campo a partir de los bodies vistos en los logs."""
    result = {}
    if df is None or df.empty or "body" not in df.columns:
        return result

    with_body = df.dropna(subset=["body"])           # solo las peticiones que llevan body
    for (method, endpoint), group in with_body.groupby(["method", "endpoint"]):
        bodies = []
        for body in group["body"]:
            if isinstance(body, dict):
                bodies.append(body)
        if not bodies:
            continue

        # Juntamos los valores de cada campo: {"amount": [55.6, 200.0, ...], "concept": ["luz", ...]}
        values = {}
        for body in bodies:
            for name, value in body.items():
                if name not in values:
                    values[name] = []
                values[name].append(value)

        fields = {}
        for name, field_values in values.items():
            presence = len(field_values) / len(bodies)
            fields[name] = field_model(name, field_values, presence)
        result[method + " " + endpoint] = fields
    return result


def field_model(name, values, presence):
    """Modelo de un campo: "number" si todos sus valores son números (y no es un id), si no "choice"."""
    numbers = []
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numbers.append(value)

    all_numbers = len(numbers) == len(values)
    if all_numbers and not ID_FIELD.search(name):
        decimals = 0
        for number in numbers:
            decimals = max(decimals, decimals_of(number))
        return {
            "type": "number",
            "min": min(numbers),
            "max": max(numbers),
            "decimals": min(2, decimals),   # como mucho 2 decimales (céntimos)
            "presence": presence,
        }
    return {"type": "choice", "values": distribution(values), "presence": presence}


def decimals_of(value):
    """55.6 -> 1 ; 200.25 -> 2 ; 3 -> 0."""
    exponent = Decimal(str(value)).as_tuple().exponent
    if not isinstance(exponent, int):
        return 0                            # infinito o "no es un número"
    return max(0, -exponent)


# ---------------------------------------------------------------------------
# 4. Bodies desde el .jar: si no hay ninguno en los logs, desde los campos del DTO
# ---------------------------------------------------------------------------

NUMBER_TYPES = {"int", "long", "short", "byte", "Integer", "Long", "Short", "Byte", "BigInteger"}
DECIMAL_TYPES = {"double", "float", "Double", "Float", "BigDecimal"}


def add_bodies_from_dto(result, endpoints):
    """Añade a `result` el body de las peticiones que no tienen ninguno en los logs,
    a partir de los campos de su DTO."""
    for e in endpoints:
        if not e["body"] or not e["body"]["fields"]:
            continue                        # la petición no lleva body
        request = e["method"] + " " + e["endpoint"]
        if request in result:
            continue                        # ya tiene bodies de los logs: mandan los logs

        fields = {}
        for name, java_type in e["body"]["fields"].items():   # {"amount": "BigDecimal", ...}
            model = default_field_model(name, java_type)
            if model is not None:
                fields[name] = model
        if fields:
            result[request] = fields


def default_field_model(name, java_type):
    """Modelo de un campo sin ejemplos, según su tipo Java. None si no sabemos generarlo.

    Son SUPOSICIONES (no datos de la app): ver GUIA.md / Suposiciones.
    """
    if ID_FIELD.search(name) and java_type in NUMBER_TYPES:
        return {"type": "choice", "values": [[1, 1.0]], "presence": 1.0}       # un id que suele existir
    if java_type in NUMBER_TYPES:
        return {"type": "number", "min": 1, "max": 100, "decimals": 0, "presence": 1.0}
    if java_type in DECIMAL_TYPES:
        return {"type": "number", "min": 1, "max": 100, "decimals": 2, "presence": 1.0}
    if java_type == "String":
        return {"type": "choice", "values": [["test", 1.0]], "presence": 1.0}
    if java_type in ("boolean", "Boolean"):
        return {"type": "choice", "values": [[True, 0.5], [False, 0.5]], "presence": 1.0}
    if java_type == "LocalDate":
        return {"type": "choice", "values": [["2026-01-01", 1.0]], "presence": 1.0}
    if java_type == "LocalDateTime":
        return {"type": "choice", "values": [["2026-01-01T12:00:00", 1.0]], "presence": 1.0}
    return None                             # listas, objetos anidados...: no se generan
