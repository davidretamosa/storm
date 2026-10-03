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


def paths_of(annotation):
    """Rutas de una anotación: @GetMapping("/{id}") -> ["/{id}"] ; @GetMapping -> [""]."""
    values = annotation["values"]
    paths = values.get("value") or values.get("path") or [""]
    return paths


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


def request_body(classes, method):
    """Si el método tiene un parámetro con @RequestBody, su tipo y sus campos."""
    for position, annotations in enumerate(method["param_annotations"]):
        for annotation in annotations:
            if annotation["type"] == SPRING + "RequestBody":
                body_type = method["params"][position]
                return {"type": body_type, "fields": dto_fields(classes, body_type)}
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

        # 2. Prefijo de la clase: @RequestMapping("/api/accounts")
        prefixes = [""]
        for annotation in info["annotations"]:
            if annotation["type"] == SPRING + "RequestMapping":
                prefixes = paths_of(annotation)

        # 3. Cada método con @GetMapping, @PostMapping... es un endpoint
        for method in info["methods"]:
            for annotation in method["annotations"]:
                if annotation["type"] not in MAPPINGS:
                    continue
                http_methods = [MAPPINGS[annotation["type"]]]
                if http_methods == [None]:  # @RequestMapping(method = RequestMethod.GET)
                    http_methods = annotation["values"].get("method") or ["GET"]

                for prefix in prefixes:
                    for path in paths_of(annotation):
                        for http_method in http_methods:
                            endpoints.append({
                                "method": http_method,
                                "endpoint": join_paths(prefix, path),
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
