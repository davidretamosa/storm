"""Correlación: que cada usuario virtual reutilice los ids que le devuelve la app.

Sin correlación, cada petición elige sus ids entre los vistos en los logs. Con correlación:

    POST /api/accounts  ->  la app responde {"id": 47, ...}  ->  el usuario apunta "mi cuenta = 47"
    POST /api/accounts/{id}/deposit        ->  usa 47 (en vez de un id de los logs)
    POST /api/transfers {"fromAccountId"}  ->  usa 47

Aquí solo se calcula QUÉ se relaciona con qué, mirando las rutas. Lo de apuntar y reutilizar
los ids lo hace JMeter mientras corre la prueba (jmx_generator/templates/*.groovy).
Si la respuesta no trae "id", o el usuario aún no ha creado nada, todo sigue como antes.
"""
import re

from traffic_model.payloads import ID_FIELD, PATH_PARAM


def created_resource(state):
    """'POST /api/accounts' -> '/api/accounts' (un POST sin {parámetros} crea algo); si no, None."""
    method, endpoint = state.split(" ", 1)
    if method == "POST" and not PATH_PARAM.search(endpoint):
        return endpoint
    return None


def resource_of_param(endpoint, param):
    """El recurso al que pertenece un {parámetro}: lo que va justo antes en la ruta.

    '/api/accounts/{id}/deposit', 'id' -> '/api/accounts'
    """
    before = endpoint.split("{" + param + "}")[0]
    return before.rstrip("/")


def resource_of_field(field, resources):
    """El recurso al que pertenece un campo id del body, por su nombre.

    'userId' -> '/api/users' ; 'fromAccountId' -> '/api/accounts' ; 'id' -> None
    """
    base = re.sub(r"(_id|Id|ID)$", "", field).lower()      # "fromAccountId" -> "fromaccount"
    if not base:
        return None
    for resource in sorted(resources):
        segment = resource.rstrip("/").split("/")[-1].lower()   # "/api/accounts" -> "accounts"
        singular = segment[:-1] if segment.endswith("s") else segment
        if base.endswith(singular):
            return resource
    return None


def build_correlation(model, bodies):
    """Qué peticiones crean algo y qué ids (de la ruta o del body) pueden reutilizar lo creado:

    {"creates":        {"POST /api/accounts": "/api/accounts", ...},
     "path_resources": {"POST /api/accounts/{id}/deposit": {"id": "/api/accounts"}, ...},
     "body_resources": {"POST /api/transfers": {"fromAccountId": "/api/accounts"}, ...}}
    """
    # 1. Las peticiones que crean algo
    creates = {}
    for state in model["states"]:
        resource = created_resource(state)
        if resource:
            creates[state] = resource
    resources = set(creates.values())

    # 2. Los {parámetros} de las rutas que son de un recurso que se puede crear
    path_resources = {}
    for state in model["states"]:
        endpoint = state.split(" ", 1)[1]
        for param in PATH_PARAM.findall(endpoint):
            resource = resource_of_param(endpoint, param)
            if resource in resources:
                path_resources.setdefault(state, {})[param] = resource

    # 3. Los campos id de los bodies. Solo el PRIMERO de cada recurso en cada body:
    #    en una transferencia, "fromAccountId" es mi cuenta; "toAccountId" es la de otro.
    body_resources = {}
    for state, fields in bodies.items():
        used = set()
        for name in fields:
            if not ID_FIELD.search(name):
                continue
            resource = resource_of_field(name, resources)
            if resource and resource not in used:
                used.add(resource)
                body_resources.setdefault(state, {})[name] = resource

    return {"creates": creates, "path_resources": path_resources, "body_resources": body_resources}
