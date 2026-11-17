"""Bodies realistas (capa de IA, flag --realistic-bodies): el body de una petición desde su DTO del .jar.

Cuando los logs solo guardan bodies vacíos ({}), no se puede aprender nada de ellos. Entonces el
body se construye con los campos de la clase que espera la aplicación (el DTO), con valores
sintéticos que respetan las validaciones estándar de Java. Nada de datos reales: textos
"storm-<campo>" y correos de example.com (dominio reservado por el RFC 2606, no es de nadie).

Anotaciones que se entienden (de cualquier aplicación Java, jakarta.* o javax.*):
  - @JsonProperty(access = READ_ONLY)            el campo no se envía
  - @Email                                       correo sintético
  - @Size(min, max)                              longitud del texto
  - @DecimalMin / @DecimalMax / @Min / @Max      rango numérico
  - @Positive / @PositiveOrZero                  rango numérico
  - @Column(unique = true) en una @Entity        el campo del mismo nombre no se puede repetir

No se entienden: @Pattern y las validaciones que son métodos (@AssertTrue).

Función que usa main.py:
- add_dto_bodies(bodies, tabla, endpoints, clases) -> (peticiones cambiadas, formas de los campos únicos)
"""
import math
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from traffic_model.payloads import ID_FIELD, default_field_model

# Las mismas anotaciones existen en javax.* (Java EE) y en jakarta.* (Jakarta EE)
VALIDATION = ("jakarta.validation.constraints.", "javax.validation.constraints.")
PERSISTENCE = ("jakarta.persistence.", "javax.persistence.")
JSON_PROPERTY = "com.fasterxml.jackson.annotation.JsonProperty"

TEXT_PREFIX = "storm-"
EMAIL_PREFIX = "storm."
EMAIL_SUFFIX = "@example.com"


# ---------------------------------------------------------------------------
# 1. Leer las anotaciones de los campos
# ---------------------------------------------------------------------------

def annotation(annotations, *types):
    """La primera anotación de `annotations` que es de alguno de los tipos (nombre completo), o None."""
    for item in annotations:
        if item["type"] in types:
            return item
    return None


def validation(annotations, simple_name):
    """La validación `simple_name` ("Size", "Min"...), sea de jakarta.* o de javax.*; None si no está."""
    return annotation(annotations, *(package + simple_name for package in VALIDATION))


def unique_names(classes):
    """Nombres de los campos con @Column(unique = true) en las clases @Entity.

    Se mira solo el nombre: si una entidad tiene @Column(unique = true) en "contact",
    cualquier DTO con un campo "contact" lo hereda.
    """
    entity_types = [package + "Entity" for package in PERSISTENCE]
    column_types = [package + "Column" for package in PERSISTENCE]
    names = set()
    for info in classes.values():
        if not annotation(info.get("annotations", []), *entity_types):
            continue                        # solo las entidades: un @Column suelto no vale
        for field in info["fields"]:
            column = annotation(field.get("annotations", []), *column_types)
            if column and column["values"].get("unique"):
                names.add(field["name"])
    return names


def read_only(annotations):
    """True si el campo lleva @JsonProperty(access = READ_ONLY): lo da la aplicación, no se envía."""
    json_property = annotation(annotations, JSON_PROPERTY)
    return bool(json_property) and json_property["values"].get("access") == "READ_ONLY"


# ---------------------------------------------------------------------------
# 2. Números: el rango que permiten las validaciones
# ---------------------------------------------------------------------------

def as_number(value):
    """El valor de una anotación como número (el "0.5" de @DecimalMin, el 2 de @Min); None si no lo es."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value                                       # el long de @Min, tal cual (sin perder cifras)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None     # "NaN" o "Infinity" no dicen nada


def annotated_bounds(annotations, step):
    """(mínimo, máximo) que dicen las validaciones; None donde no dicen nada.

    Con inclusive = false, el límite se mueve un `step` hacia dentro.
    """
    low = high = None
    for simple_name in ("DecimalMin", "Min"):
        found = validation(annotations, simple_name)
        value = as_number(found["values"].get("value")) if found else None
        if value is not None:
            if not found["values"].get("inclusive", True):
                value += step
            low = value if low is None else max(low, value)
    for simple_name in ("DecimalMax", "Max"):
        found = validation(annotations, simple_name)
        value = as_number(found["values"].get("value")) if found else None
        if value is not None:
            if not found["values"].get("inclusive", True):
                value -= step
            high = value if high is None else min(high, value)
    if validation(annotations, "Positive"):
        low = step if low is None else max(low, step)
    if validation(annotations, "PositiveOrZero"):
        low = 0 if low is None else max(low, 0)
    return low, high


def number_range(model, annotations):
    """El modelo numérico de default_field_model, con el rango estrechado por las validaciones.

    Si el rango por defecto no cabe en lo que piden, se mueve:
      (a) sin máximo anotado:  [mínimo, mínimo + ancho]     @DecimalMin("500")             -> [500, 599]
      (b) sin mínimo anotado:  [máximo, máximo]             @DecimalMax("0.5")             -> [0.5, 0.5]
      (c) los dos, compatibles: [mínimo, máximo]            @Positive + @DecimalMax("0.5") -> [0.01, 0.5]
      (d) contradictorias:     [mínimo, mínimo]             @DecimalMin("10") + @DecimalMax("5") -> [10, 10]
    """
    decimals = model["decimals"]
    step = 10 ** -decimals if decimals else 1
    width = model["max"] - model["min"]
    low_a, high_a = annotated_bounds(annotations, step)
    low = model["min"] if low_a is None else max(model["min"], low_a)
    high = model["max"] if high_a is None else min(model["max"], high_a)
    if low > high:
        if high_a is None:                      # (a)
            high = low + width
        elif low_a is None:                     # (b)
            low = high = high_a
        elif low_a <= high_a:                   # (c)
            low, high = low_a, high_a
        else:                                   # (d)
            low = high = low_a
    low, high = inward(low, decimals, up=True), inward(high, decimals, up=False)
    if low > high:                              # ningún valor con esos decimales cabe en [low, high]
        if low_a is None:
            low = high                          # solo hay máximo: el máximo, que sí cumple
        else:
            high = low                          # hay mínimo: el mínimo, como en (d)
    return {**model, "min": low, "max": high}


def inward(value, decimals, up):
    """Redondea a `decimals` hacia dentro del rango: el mínimo hacia arriba y el máximo hacia abajo.

    Si algún valor con esos decimales cumple las validaciones, el rango solo tiene valores que la
    validación acepta: @DecimalMax("9.5") en un entero -> 9. Se redondea en decimal, no en binario,
    para que 0.57 no se convierta en 0.56. Los números sin decimales quedan enteros.
    """
    if isinstance(value, float):
        value = repr(round(value, 12))          # quita el ruido de las restas: 0.30000000000000004 -> 0.3
    exact = Decimal(value).quantize(Decimal(1).scaleb(-decimals),
                                    rounding=ROUND_CEILING if up else ROUND_FLOOR)
    return int(exact) if decimals == 0 else float(exact)


# ---------------------------------------------------------------------------
# 3. Textos: un valor fijo y la "forma" para hacerlo único (la usan el T-3.3 y el T-3.4)
# ---------------------------------------------------------------------------

def fixed_value(form, middle="storm"):
    """prefix + middle + suffix, con la longitud que pide la forma.

    Con "max" se conserva `middle` (en el T-3.4 es la marca que hace único el valor): se acorta antes
    el prefijo, y `middle` solo si no cabe ni sin prefijo. Con "min", se rellena con "x" justo después
    del prefijo.
    """
    prefix, suffix = form["prefix"], form["suffix"]
    if form.get("max") is not None:
        high = int(form["max"])
        middle = middle[:max(0, high - len(suffix))]
        prefix = prefix[:max(0, high - len(middle) - len(suffix))]
    value = prefix + middle + suffix
    if form.get("min") is not None and len(value) < int(form["min"]):
        value = prefix + "x" * (int(form["min"]) - len(value)) + middle + suffix
    if form.get("max") is not None:
        value = value[:int(form["max"])]        # si ni el sufijo cabe, se corta también
    return value


def text_model(name, annotations):
    """(valor, forma) de un campo String.

    - sin @Email: valor "storm-<nombre>", forma {"prefix": "storm-<nombre>-", "suffix": ""};
    - con @Email: forma {"prefix": "storm.", "suffix": "@example.com"} y valor fixed_value(forma);
    - @Size(min, max): el valor se alarga con "x" hasta min y se acorta hasta max; la forma los lleva.
    """
    address = validation(annotations, "Email")
    value = TEXT_PREFIX + name
    if address:
        form = {"prefix": EMAIL_PREFIX, "suffix": EMAIL_SUFFIX}
    else:
        form = {"prefix": value + "-", "suffix": ""}
    size = validation(annotations, "Size")
    if size:
        values = size["values"]
        if values.get("min") is not None:
            form["min"] = int(values["min"])
            value = value.ljust(form["min"], "x")
        if values.get("max") is not None:
            form["max"] = int(values["max"])
            value = value[:form["max"]]
    if address:
        value = fixed_value(form)
    return value, form


# ---------------------------------------------------------------------------
# 4. El body del DTO y la sustitución en el modelo de bodies
# ---------------------------------------------------------------------------

def dto_body(classes, class_name, unique=frozenset()):
    """(campos, formas únicas) del DTO `class_name`, o None si la clase no está en el .jar.

    campos: {"contact": {"type": "choice", "values": [["storm.storm@example.com", 1.0]], "presence": 1.0},
             "sourceId": {"type": "choice", "values": [[1, 1.0]], "presence": 1.0}, ...}
    formas únicas: {"contact": {"prefix": "storm.", "suffix": "@example.com"}, ...}

    Se saltan los campos static y los READ_ONLY. Los que no se saben generar (listas, objetos) no van.
    """
    info = classes.get(class_name)
    if info is None:
        return None
    fields, unique_forms = {}, {}
    for field in info["fields"]:
        name, annotations = field["name"], field.get("annotations", [])
        if field["static"] or read_only(annotations):
            continue
        java_type = field["type"].split(".")[-1]       # java.lang.String -> String
        if java_type == "String":
            value, form = text_model(name, annotations)
            fields[name] = {"type": "choice", "values": [[value, 1.0]], "presence": 1.0}
            if name in unique and not ID_FIELD.search(name):   # un id lo da la aplicación, no el plan
                unique_forms[name] = form
            continue
        model = default_field_model(name, java_type)
        if model is None:
            continue
        if model["type"] == "number":
            model = number_range(model, annotations)
        fields[name] = model
    return fields, unique_forms


def requests_with_fields(df):
    """{"POST /items", ...}: las peticiones con algún body de los logs (de cualquier status) con campos."""
    result = set()
    if df is None or df.empty or "body" not in df.columns:
        return result
    for method, endpoint, body in zip(df["method"], df["endpoint"], df["body"]):
        if isinstance(body, dict) and body:
            result.add(method + " " + endpoint)
    return result


def add_dto_bodies(bodies, df, endpoints, classes):
    """Cambia en `bodies` el modelo de las peticiones que nunca llevan campos en los logs por el de su DTO.

    Solo las que ya están en `bodies` (así no cambia qué peticiones llevan body): las de los logs con {}
    y las que solo están en el .jar. Si la petición sale dos veces en `endpoints`, manda la primera.

    Devuelve (peticiones cambiadas, ordenadas; {petición: {campo: forma}} de las que tienen campos únicos).
    """
    replaced, forms = [], {}
    if not endpoints or not classes:
        return replaced, forms
    taught = requests_with_fields(df)
    unique = unique_names(classes)
    seen = set()
    for e in endpoints:
        body = e.get("body")
        if not body or not body.get("type"):
            continue
        request = e["method"] + " " + e["endpoint"]
        if request in seen:
            continue                        # sale dos veces: manda la primera
        seen.add(request)
        if request not in bodies or request in taught:
            continue                        # no lleva body, o los logs lo enseñan: mandan los logs
        built = dto_body(classes, body["type"], unique)
        if built is None or not built[0]:
            continue                        # el DTO no está o no tiene campos que se sepan generar
        fields, unique_forms = built
        bodies[request] = fields
        replaced.append(request)
        if unique_forms:
            forms[request] = unique_forms
    return sorted(replaced), forms
