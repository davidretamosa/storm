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

from traffic_model.regex_sample import sample as regex_sample

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
            path = path.split("?")[0]                # "/api/accounts/1/transactions?page=0" -> sin "?page=0"
            match = regex.match(path)
            if match:
                for name in params:
                    values[name].append(match[name])  # "3", "4"...

        request = method + " " + endpoint
        result[request] = {}
        for name in params:
            result[request][name] = distribution(values[name])
    return result

def build_query_params(df):
    """Aprende las combinaciones de parámetros de consulta por petición."""
    result = {}

    if df is None or df.empty or "query" not in df.columns:
        return result

    for (method, endpoint), group in df.groupby(["method", "endpoint"]):
        values = group["query"].fillna("").tolist()

        # Solo modelamos peticiones con parámetros de consulta
        if any(values):
            request = method + " " + endpoint
            result[request] = distribution(values)

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
        schema = e["body"].get("schema")
        if schema:
            # Con el esquema del .jar: tipos, listas, objetos y reglas de validación
            for name, entry in schema.items():
                model = schema_field_model(name, entry)
                if model is not None:
                    fields[name] = model
        else:
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


# ---------------------------------------------------------------------------
# 5. Bodies desde el .jar con sus reglas de validación (@Pattern, @Size, @Min, @Email...)
# ---------------------------------------------------------------------------

# Fecha de ejemplo: ni pasada ni futura si el DTO no dice nada; 2030 si pide @Future; 2020 si pide @Past
SAMPLE_DATES = {"neutral": (2026, 6, 15), "future": (2030, 6, 15), "past": (2020, 6, 15)}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
DATE_TYPES = {"LocalDate", "LocalDateTime", "LocalTime", "Instant", "OffsetDateTime", "ZonedDateTime", "Date"}
TEXT_TYPES = {"String", "CharSequence", "UUID"}


def format_java_date(pattern, year, month, day):
    """Escribe una fecha (a las 14:30:45) con un patrón de Java: 'dd/MM/yyyy' -> '15/06/2030'."""
    out = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "'":                                   # texto literal entre comillas simples
            end = pattern.find("'", i + 1)
            if end == -1:
                break
            out.append(pattern[i + 1:end] or "'")
            i = end + 1
            continue
        if not char.isalpha():
            out.append(char)
            i += 1
            continue
        count = 1
        while i + count < len(pattern) and pattern[i + count] == char:
            count += 1
        i += count
        if char in "yu":
            out.append(f"{year % 100:02d}" if count == 2 else f"{year:0{count}d}")
        elif char in "ML":
            out.append(MONTHS[month - 1][:3] if count == 3 else MONTHS[month - 1] if count > 3 else f"{month:0{count}d}")
        elif char == "d":
            out.append(f"{day:0{count}d}")
        elif char == "H":
            out.append(f"{14:0{count}d}")
        elif char == "h":
            out.append(f"{2:0{count}d}")
        elif char == "m":
            out.append(f"{30:0{count}d}")
        elif char == "s":
            out.append(f"{45:0{count}d}")
        elif char == "S":
            out.append("0" * count)
        elif char == "a":
            out.append("PM")
        elif char == "X":
            out.append("Z")
        elif char in "Zx":
            out.append("+0000")
        else:
            out.append(char * count)
    return "".join(out)


def date_value(java_type, rules):
    """Fecha o fecha-hora de ejemplo, con el formato que pida @JsonFormat y respetando @Future/@Past."""
    kind = "future" if rules.get("future") else "past" if rules.get("past") else "neutral"
    year, month, day = SAMPLE_DATES[kind]
    if rules.get("format"):
        return format_java_date(rules["format"], year, month, day)
    date = f"{year}-{month:02d}-{day:02d}"
    if java_type == "LocalDate":
        return date
    if java_type == "LocalTime":
        return "14:30:45"
    if java_type == "LocalDateTime":
        return date + "T14:30:45"
    return date + "T14:30:45Z"                  # Instant, OffsetDateTime, ZonedDateTime, Date


def text_value(java_type, name, rules):
    """Un texto que cumple @Pattern, @Email y @Size."""
    min_len = rules.get("min_len", 0)
    max_len = rules.get("max_len")
    if java_type == "UUID":
        return "123e4567-e89b-12d3-a456-426614174000"
    if rules.get("pattern"):
        value = regex_sample(rules["pattern"], min_len, max_len)
        if value is not None:
            return value
    if rules.get("email") or "email" in name.lower() and not rules.get("pattern"):
        value = "test@example.com"
    else:
        value = "test"
    if len(value) < min_len:
        value = value + "x" * (min_len - len(value))
    if max_len is not None and len(value) > max_len:
        value = value[:max_len]
    return value


def number_model(java_type, rules):
    """Número entre el mínimo y el máximo que declare el DTO (por defecto, de 1 a 100)."""
    decimal = java_type in DECIMAL_TYPES
    low, high = rules.get("min"), rules.get("max")
    if low is None and high is None:
        low, high = 1, 100
    elif high is None:
        high = low + 99
    elif low is None:
        low = min(1, high)
        if low > high - 1 and high < 1:
            low = high - 99
    if low > high:
        low = high
    if not decimal:
        low, high = int(-(-low // 1)), int(high // 1)
    decimals = min(2, rules.get("decimals", 2)) if decimal else 0
    return {"type": "number", "min": low, "max": high, "decimals": decimals, "presence": 1.0}


def static_value(model):
    """Un valor fijo a partir del modelo de un campo (para meter dentro de listas y objetos)."""
    if model["type"] == "number":
        value = model["min"]
        return float(value) if model["decimals"] else int(value)
    return model["values"][0][0]


def schema_field_model(name, entry):
    """Modelo de un campo a partir de su entrada del esquema del .jar. None si no sabemos generarlo."""
    java_type = entry["type"]
    rules = entry.get("rules", {})

    if entry.get("collection"):
        # Lista vacía, salvo que el DTO pida al menos un elemento (@NotEmpty, @Size(min=1))
        items = []
        element = entry.get("element")
        if rules.get("min_len", 0) >= 1 and element:
            model = schema_field_model(name, element)
            if model is not None:
                items = [static_value(model)]
        return {"type": "choice", "values": [[items, 1.0]], "presence": 1.0}

    if entry.get("enum"):
        constants = entry["enum"]
        return {"type": "choice", "values": [[value, 1 / len(constants)] for value in constants], "presence": 1.0}

    if entry.get("fields") is not None:
        nested = {}
        for field_name, field_entry in entry["fields"].items():
            model = schema_field_model(field_name, field_entry)
            if model is not None:
                nested[field_name] = static_value(model)
        return {"type": "choice", "values": [[nested, 1.0]], "presence": 1.0}

    if ID_FIELD.search(name) and java_type in NUMBER_TYPES:
        return {"type": "choice", "values": [[1, 1.0]], "presence": 1.0}    # un id que suele existir
    if java_type in NUMBER_TYPES or java_type in DECIMAL_TYPES:
        return number_model(java_type, rules)
    if java_type in TEXT_TYPES:
        return {"type": "choice", "values": [[text_value(java_type, name, rules), 1.0]], "presence": 1.0}
    if java_type in DATE_TYPES:
        return {"type": "choice", "values": [[date_value(java_type, rules), 1.0]], "presence": 1.0}
    return default_field_model(name, java_type)
