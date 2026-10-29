"""Bodies realistes (T-3): el body d'una petició a partir del seu DTO al .jar, amb les validacions.

Quan el log desa un body buit ({}), no se'n pot aprendre res: es construeix des dels camps de la
classe que l'app espera (el DTO), amb valors sintètics que respecten el que les anotacions estàndard
de Java permeten llegir. Res de dades reals: textos "storm-<camp>" i correus a example.com
(domini reservat, no és de ningú).

El jar_parser dels companys (parse_jar) dona el nom i el tipus de cada camp, però no les seves
anotacions: el seu read_class les llegeix i les llença. Aquí es fa el mateix recorregut del .class
cridant les seves funcions (jar_parser/class_file.py) i guardant les anotacions dels camps.

Anotacions que s'entenen (de qualsevol app Java):
  - @JsonProperty(access = READ_ONLY)                 el camp no s'envia
  - @Email                                            correu sintètic
  - @Size(min, max)                                   llargada del text
  - @DecimalMin / @DecimalMax / @Min / @Max           rang numèric (@Min i @Max només si el valor es pot llegir)
  - @Positive / @PositiveOrZero                       rang numèric
  - @Column(unique = true) a una classe @Entity       el camp del mateix nom es fa únic

No s'entenen (vegeu l'informe): @Pattern i les validacions que són mètodes (@AssertTrue).
"""
import zipfile

from jar_parser.class_file import Reader, descriptor_to_type, read_attributes, read_constant_pool
from traffic_model.payloads import default_field_model

ACC_STATIC = 0x0008

# Paquets estàndard: les mateixes anotacions existeixen amb javax.* (Java EE) i jakarta.* (Jakarta EE)
VALIDATION = ("jakarta.validation.constraints.", "javax.validation.constraints.")
PERSISTENCE = ("jakarta.persistence.", "javax.persistence.")
JSON_PROPERTY = "com.fasterxml.jackson.annotation.JsonProperty"

EMAIL_PREFIX = "storm."
EMAIL_SUFFIX = "@example.com"


# ---------------------------------------------------------------------------
# 1. Llegir el .jar: classes, camps i les anotacions de cada camp
# ---------------------------------------------------------------------------

def read_class(data):
    """Com jar_parser.class_file.read_class, però guardant les anotacions de cada camp:

    {"name": ..., "annotations": [...], "fields": [{"name", "type", "static", "annotations"}, ...]}
    """
    reader = Reader(data)
    if reader.u4() != 0xCAFEBABE:
        raise ValueError("No és un fitxer .class")
    reader.u2()  # versió menor
    reader.u2()  # versió major
    pool = read_constant_pool(reader)

    reader.u2()  # modificadors
    name = pool[pool[reader.u2()][1]].replace("/", ".")
    reader.u2()  # superclasse
    for _ in range(reader.u2()):  # interfícies
        reader.u2()

    fields = []
    for _ in range(reader.u2()):
        access = reader.u2()
        field_name = pool[reader.u2()]
        field_type = descriptor_to_type(pool[reader.u2()])
        annotations = read_attributes(reader, pool)["annotations"]
        fields.append({"name": field_name, "type": field_type, "static": bool(access & ACC_STATIC),
                       "annotations": annotations})

    for _ in range(reader.u2()):  # mètodes: es llegeixen per arribar a les anotacions de la classe
        reader.u2()
        reader.u2()
        reader.u2()
        read_attributes(reader, pool)

    return {"name": name, "annotations": read_attributes(reader, pool)["annotations"], "fields": fields}


def read_classes(jar_path):
    """{nom de la classe: classe llegida}, sense les llibreries que porta dins (BOOT-INF/lib/)."""
    classes = {}
    with zipfile.ZipFile(jar_path) as jar:
        for entry in jar.namelist():
            if entry.endswith(".class") and not entry.startswith("BOOT-INF/lib/"):
                info = read_class(jar.read(entry))
                classes[info["name"]] = info
    return classes


def annotation(annotations, *types):
    """La primera anotació de `annotations` que és d'algun dels tipus (nom complet), o None."""
    for item in annotations:
        if item["type"] in types:
            return item
    return None


def validation(annotations, simple_name):
    return annotation(annotations, *(package + simple_name for package in VALIDATION))


def unique_names(classes):
    """Noms dels camps marcats @Column(unique = true) a les classes @Entity."""
    names = set()
    for info in classes.values():
        if not annotation(info["annotations"], *(package + "Entity" for package in PERSISTENCE)):
            continue
        for field in info["fields"]:
            column = annotation(field["annotations"], *(package + "Column" for package in PERSISTENCE))
            if column and column["values"].get("unique"):
                names.add(field["name"])
    return names


# ---------------------------------------------------------------------------
# 2. El model de cada camp, en el format de traffic_model/payloads.py
# ---------------------------------------------------------------------------

def read_only(annotations):
    json_property = annotation(annotations, JSON_PROPERTY)
    return bool(json_property) and json_property["values"].get("access") == "READ_ONLY"


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None   # p. ej. @Min/@Max, que el lector dels companys no llegeix (valors long)


def annotated_bounds(annotations, step):
    """(mínim, màxim) que diuen les validacions; None si no en diuen res."""
    low = high = None
    for simple_name in ("DecimalMin", "Min"):
        found = validation(annotations, simple_name)
        value = _number(found["values"].get("value")) if found else None
        if value is not None:
            value = value if found["values"].get("inclusive", 1) else value + step
            low = value if low is None else max(low, value)
    for simple_name in ("DecimalMax", "Max"):
        found = validation(annotations, simple_name)
        value = _number(found["values"].get("value")) if found else None
        if value is not None:
            value = value if found["values"].get("inclusive", 1) else value - step
            high = value if high is None else min(high, value)
    if validation(annotations, "Positive"):
        low = step if low is None else max(low, step)
    if validation(annotations, "PositiveOrZero"):
        low = 0 if low is None else max(low, 0)
    return low, high


def number_range(model, annotations):
    """El rang {"min", "max"} d'un camp numèric: el de per defecte (payloads.default_field_model),
    estret per les validacions. Si el de per defecte no hi cap, es mou cap on diuen les validacions."""
    step = 10 ** -model["decimals"] if model["decimals"] else 1
    width = model["max"] - model["min"]
    low_a, high_a = annotated_bounds(annotations, step)
    low = model["min"] if low_a is None else max(model["min"], low_a)
    high = model["max"] if high_a is None else min(model["max"], high_a)
    if low > high:
        if high_a is None:                          # p. ej. @DecimalMin("500"): [500, 599]
            high = low + width
        elif low_a is None or low_a <= high_a:      # p. ej. @DecimalMax("0.5"): baixa fins al mínim que diuen
            low = low_a if low_a is not None else high_a
        else:                                       # validacions contradictòries: el mínim que demanen
            high = low = low_a
    return {**model, "min": low, "max": high}


def text_model(name, annotations):
    """(valor fix, forma per fer-lo únic) d'un camp de text."""
    if validation(annotations, "Email"):
        return EMAIL_PREFIX + "storm" + EMAIL_SUFFIX, {"prefix": EMAIL_PREFIX, "suffix": EMAIL_SUFFIX}
    value = "storm-" + name
    size = validation(annotations, "Size")
    form = {"prefix": value + "-", "suffix": ""}
    if size:
        # La forma porta la llargada: el PreProcessor l'ha de respectar també amb el testimoni a dins
        low, high = int(size["values"].get("min", 0)), size["values"].get("max")
        value = value.ljust(low, "x")
        if low:
            form["min"] = low
        if high is not None:
            value = value[:int(high)]
            form["max"] = int(high)
    return value, form


def dto_body(classes, class_name, unique=frozenset()):
    """(model dels camps, formes dels camps únics) del DTO `class_name`; None si no és al .jar.

    model: {"camp": {"type": ..., "presence": 1.0, ...}}  (el format de payloads.py)
    únics: {"camp": {"prefix": ..., "suffix": ...}}       (la regla "unique" de bodies_learn.py)
    """
    info = classes.get(class_name)
    if info is None:
        return None
    fields, unique_forms = {}, {}
    for field in info["fields"]:
        name, annotations = field["name"], field["annotations"]
        if field["static"] or read_only(annotations):
            continue
        java_type = field["type"].split(".")[-1]
        if java_type == "String":
            value, form = text_model(name, annotations)
            fields[name] = {"type": "choice", "values": [[value, 1.0]], "presence": 1.0}
            if name in unique:
                unique_forms[name] = form
            continue
        model = default_field_model(name, java_type)
        if model is None:
            continue
        if model["type"] == "number":
            model = number_range(model, annotations)
        fields[name] = model
    return fields, unique_forms
