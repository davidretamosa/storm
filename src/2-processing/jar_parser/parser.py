"""Descubre la API de la aplicación leyendo su .jar, sin ejecutarla (análisis estático).

De cada controller de Spring (@RestController) saca sus endpoints a partir de las anotaciones:

    @RequestMapping("/api/accounts")             <- prefijo de la clase
    public class AccountController {
        @PostMapping("/{id}/deposit")           <- método HTTP + resto de la ruta
        ... deposit(@PathVariable Long id, @RequestBody DepositRequest request)
                                                 <- el body es un DepositRequest
    }

    -> POST /api/accounts/{id}/deposit, body DepositRequest {amount: BigDecimal}

Funciona con el .jar de Spring Boot (clases en BOOT-INF/classes/) y con un .jar normal.
"""
import re
import zipfile

from jar_parser.class_file import read_class

SPRING = "org.springframework.web.bind.annotation."
CONTROLLERS = [SPRING + "RestController", "org.springframework.stereotype.Controller"]

# Anotación -> método HTTP. @RequestMapping lleva el método dentro: method = RequestMethod.GET
MAPPINGS = {
    SPRING + "GetMapping": "GET",
    SPRING + "PostMapping": "POST",
    SPRING + "PutMapping": "PUT",
    SPRING + "DeleteMapping": "DELETE",
    SPRING + "PatchMapping": "PATCH",
    SPRING + "RequestMapping": None,
}

# ${propiedad:valor por defecto} -> valor por defecto (las interfaces generadas lo usan)
PLACEHOLDER = re.compile(r"\$\{[^}:]*(?::([^}]*))?\}")

def read_jar_classes(jar_path):
    """Lee todas las clases de la aplicación que hay dentro del .jar.

    Devuelve {nombre de la clase: clase leída}. Se saltan las librerías que el .jar de
    Spring Boot lleva dentro (BOOT-INF/lib/), porque no son código de la aplicación.
    """
    classes = {}
    with zipfile.ZipFile(jar_path) as jar:
        for name in jar.namelist():
            if not name.endswith(".class") or name.startswith("BOOT-INF/lib/"):
                continue
            info = read_class(jar.read(name))
            classes[info["name"]] = info
    return classes

def resolve_placeholders(path):
    """'${openapi.api.base-path:/api}/owners' -> '/api/owners' (usa el valor por defecto)."""
    return PLACEHOLDER.sub(lambda match: match.group(1) or "", path)

def paths_of(annotation):
    """Rutas de una anotación: @GetMapping("/{id}") -> ["/{id}"] ; @GetMapping -> [""]."""
    values = annotation["values"]
    paths = values.get("value") or values.get("path") or [""]
    if isinstance(paths, str):
        paths = [paths]
    return [resolve_placeholders(path) for path in paths]

def http_methods_of(annotation):
    """Métodos HTTP de una anotación: @PostMapping -> ["POST"] ; @RequestMapping(method=GET) -> ["GET"]."""
    method = MAPPINGS[annotation["type"]]
    if method is not None:
        return [method]
    methods = annotation["values"].get("method") or ["GET"]
    return methods if isinstance(methods, list) else [methods]


def class_prefixes(info):
    """Prefijos del @RequestMapping de una clase o interfaz; [] si no tiene."""
    for annotation in info["annotations"]:
        if annotation["type"] == SPRING + "RequestMapping":
            return paths_of(annotation)
    return []


def all_interfaces(classes, info, seen=None):
    """Interfaces de una clase (y las que extienden esas) que están dentro del .jar."""
    seen = seen if seen is not None else []
    for name in info.get("interfaces", []):
        if name in classes and name not in seen:
            seen.append(name)
            all_interfaces(classes, classes[name], seen)
    return seen


def join_paths(prefix, path):
    """'/api/accounts' + '/{id}/deposit' -> '/api/accounts/{id}/deposit'."""
    full = "/" + prefix.strip("/") + "/" + path.strip("/")
    full = full.replace("//", "/")
    if len(full) > 1:
        full = full.rstrip("/")
    return full


def dto_fields(classes, class_name):
    """Campos de un DTO: {"amount": "BigDecimal", ...}. None si la clase no está en el .jar."""
    if class_name not in classes:
        return None
    fields = {}
    for field in classes[class_name]["fields"]:
        if not field["static"]:
            fields[field["name"]] = field["type"].split(".")[-1]  # java.math.BigDecimal -> BigDecimal
    return fields


# ---------------------------------------------------------------------------
# Esquema de un DTO: tipo de cada campo y sus reglas de validación (@Pattern, @Size, @Min...)
# ---------------------------------------------------------------------------

VALIDATION = ("jakarta.validation.constraints.", "javax.validation.constraints.")
COLLECTIONS = {
    "java.util.List", "java.util.Set", "java.util.Collection", "java.util.ArrayList",
    "java.util.HashSet", "java.util.LinkedList", "java.util.SortedSet", "java.util.LinkedHashSet",
}
MAX_DEPTH = 3   # niveles de objetos dentro de objetos


def field_rules(annotations):
    """Reglas de validación que declaran las anotaciones de un campo (o de su getter):

    [@Pattern(regexp="^[0-9]*$"), @Size(max=20)] -> {"pattern": "^[0-9]*$", "max_len": 20}

    min/max valen para números; min_len/max_len, para textos y listas.
    """
    rules = {}

    def lower(key, value):
        rules[key] = value if key not in rules else max(rules[key], value)

    def upper(key, value):
        rules[key] = value if key not in rules else min(rules[key], value)

    for annotation in annotations:
        full = annotation["type"]
        name = full.split(".")[-1]
        values = annotation["values"]
        if full.startswith(VALIDATION):
            if name == "Pattern" and values.get("regexp"):
                rules["pattern"] = values["regexp"]
            elif name == "Size":
                if values.get("min", 0) > 0:
                    lower("min_len", values["min"])
                if "max" in values:
                    upper("max_len", values["max"])
            elif name == "Min":
                lower("min", values.get("value", 0))
            elif name == "Max":
                upper("max", values.get("value", 0))
            elif name in ("DecimalMin", "DecimalMax"):
                try:
                    number = float(values.get("value"))
                except (TypeError, ValueError):
                    continue
                (lower if name == "DecimalMin" else upper)("min" if name == "DecimalMin" else "max", number)
            elif name == "Positive":
                lower("min", 1)
            elif name == "PositiveOrZero":
                lower("min", 0)
            elif name == "Negative":
                upper("max", -1)
            elif name == "NegativeOrZero":
                upper("max", 0)
            elif name == "Digits":
                rules["decimals"] = values.get("fraction", 0)
            elif name == "Email":
                rules["email"] = True
            elif name == "NotBlank":
                lower("min_len", 1)
            elif name == "NotEmpty":
                lower("min_len", 1)
            elif name == "Future" or name == "FutureOrPresent":
                rules["future"] = True
            elif name == "Past" or name == "PastOrPresent":
                rules["past"] = True
        elif name == "JsonFormat" and values.get("pattern"):
            rules["format"] = values["pattern"]
        elif name == "DateTimeFormat" and (values.get("pattern") or values.get("value")):
            rules.setdefault("format", values.get("pattern") or values.get("value"))
    return rules


def json_name(annotations, default):
    """Nombre del campo en el JSON: el de @JsonProperty("x") si lo lleva."""
    for annotation in annotations:
        if annotation["type"].endswith(".JsonProperty") and annotation["values"].get("value"):
            return annotation["values"]["value"]
    return default


def element_type(type_name, signature):
    """De qué son los elementos de una lista: List<Role> -> 'com.x.Role' ; Role[] -> 'com.x.Role'."""
    if type_name.endswith("[]"):
        return type_name[:-2]
    match = re.search(r"<[+*-]?L([^<;]+)", signature or "")
    return match.group(1).replace("/", ".") if match else None


def type_info(classes, type_name, signature, depth, stack):
    """Qué es un tipo: texto, número, lista (de qué), enum (qué valores) u objeto (qué campos)."""
    info = {"type": type_name.split(".")[-1]}
    if type_name in COLLECTIONS or type_name.endswith("[]"):
        info["collection"] = True
        element = element_type(type_name, signature)
        info["element"] = type_info(classes, element, None, depth + 1, stack) if element else None
        return info
    cls = classes.get(type_name)
    if cls is not None and depth <= MAX_DEPTH and type_name not in stack:
        constants = [f["name"] for f in cls["fields"] if f["enum"]]
        if constants:
            info["enum"] = constants
        else:
            info["fields"] = dto_schema(classes, type_name, depth + 1, stack + (type_name,))
    return info


def dto_schema(classes, class_name, depth=0, stack=()):
    """Campos de un DTO con su tipo y sus reglas de validación. None si la clase no está en el .jar.

    {"telephone": {"type": "String", "rules": {"pattern": "^[0-9]*$", "max_len": 20}},
     "specialties": {"type": "List", "collection": True, "element": {...}, "rules": {}}, ...}

    Incluye los campos heredados. Las reglas se leen del campo y de su getter (los DTO generados
    por OpenAPI llevan las anotaciones en el getter).
    """
    if class_name not in classes:
        return None
    chain = []
    current = class_name
    while current in classes and current not in chain:
        chain.insert(0, current)         # primero la clase de arriba (la que se hereda)
        current = classes[current].get("super")

    schema = {}
    for owner in chain:
        info = classes[owner]
        getters = {m["name"]: m["annotations"] for m in info["methods"]}
        for field in info["fields"]:
            if field["static"] or field["enum"]:
                continue
            cap = field["name"][:1].upper() + field["name"][1:]
            annotations = field["annotations"] + getters.get("get" + cap, []) + getters.get("is" + cap, [])
            entry = type_info(classes, field["type"], field["signature"], depth, stack + (class_name,))
            entry["rules"] = field_rules(annotations)
            schema[json_name(annotations, field["name"])] = entry
    return schema


def request_body(classes, method):
    """Si el método tiene un parámetro con @RequestBody, su tipo y sus campos."""
    for position, annotations in enumerate(method["param_annotations"]):
        for annotation in annotations:
            if annotation["type"] == SPRING + "RequestBody":
                body_type = method["params"][position]
                return {
                    "type": body_type,
                    "fields": dto_fields(classes, body_type),
                    "schema": dto_schema(classes, body_type),
                }
    return None


def parse_jar(jar_path):
    """Lista de endpoints de la aplicación, p. ej.:

    [{"method": "POST", "endpoint": "/api/accounts/{id}/deposit",
      "controller": "com.pae.bankapp.controller.AccountController", "handler": "deposit",
      "body": {"type": "com.pae.bankapp.dto.DepositRequest", "fields": {"amount": "BigDecimal"}}},
     ...]
    """
    classes = read_jar_classes(jar_path)
    endpoints = []

    for class_name, info in classes.items():
        # 1. Solo los controllers
        class_types = [a["type"] for a in info["annotations"]]
        if not any(controller in class_types for controller in CONTROLLERS):
            continue

        # 2. Prefijo de la clase: @RequestMapping("/api/accounts"), si no tiene, el de la interfaz
        own_prefixes = class_prefixes(info)
        sources = [(info, own_prefixes)]
        for interface_name in all_interfaces(classes, info):
            interface = classes[interface_name]
            sources.append((interface, own_prefixes or class_prefixes(interface)))

        # 3. Cada método con @GetMapping, @PostMapping... es un endpoint
        found = set()
        for source, prefixes in sources:
            for method in source["methods"]:
                for annotation in method["annotations"]:
                    if annotation["type"] not in MAPPINGS:
                        continue
                    for prefix in prefixes or [""]:
                        for path in paths_of(annotation):
                            for http_method in http_methods_of(annotation):
                                endpoint = join_paths(prefix, path)
                                if (http_method, endpoint) in found:  # ya visto (p. ej. método repetido)
                                    continue
                                found.add((http_method, endpoint))
                                endpoints.append({
                                    "method": http_method,
                                    "endpoint": endpoint,
                                    "controller": class_name,
                                    "handler": method["name"],
                                    "body": request_body(classes, method),
                                })

    endpoints.sort(key=lambda e: (e["endpoint"], e["method"]))
    return endpoints


def compare_with_logs(endpoints, df):
    """Cruza la API del .jar con lo que aparece en los logs:

    - never_used: endpoints que existen en el .jar pero nadie ha usado en los logs
      (el .jmx no los probará, porque la cadena de Markov solo conoce lo observado).
    - unknown: peticiones de los logs que no están en el .jar (¿.jar antiguo? ¿error en el log?).
    """
    in_jar = set()
    for e in endpoints:
        in_jar.add(e["method"] + " " + e["endpoint"])

    in_logs = set(df["method"] + " " + df["endpoint"])
    return {
        "never_used": sorted(in_jar - in_logs),
        "unknown": sorted(in_logs - in_jar),
    }
