
"""Correlación: que cada usuario virtual reutilice los ids que le devuelve la app.

La correlación admite dos estilos de API:

1. REST clásico:
   POST /api/accounts -> GET /api/accounts/{id}

2. APIs con verbos en las rutas:
   POST /api/events/addevent -> GET /api/events/getevent/{event_id}

También admite parámetros genéricos como {id}, comparando los recursos
presentes en las rutas de creación y consulta.
"""

import re

from traffic_model.payloads import ID_FIELD, PATH_PARAM


# Verbos habituales que aparecen dentro de las rutas de las APIs.
OPERATION_PREFIXES = (
    "create",
    "add",
    "get",
    "find",
    "fetch",
    "read",
    "delete",
    "remove",
    "update",
    "edit",
    "register",
    "list",
)


def created_resource(state):
    """Identifica los POST que crean recursos.

    Ejemplos:
        POST /api/accounts
            -> /api/accounts

        POST /api/attendees/addattendee/{eventId}
            -> /api/attendees/addattendee

        POST /api/accounts/{id}/deposit
            -> None
    """
    method, endpoint = state.split(" ", 1)

    if method != "POST":
        return None

    # Los POST sin parámetros mantienen el comportamiento anterior.
    if not PATH_PARAM.search(endpoint):
        return endpoint

    # Eliminamos los parámetros para analizar los segmentos de la ruta.
    route = PATH_PARAM.sub("", endpoint).rstrip("/")
    segments = route.strip("/").split("/")

    if len(segments) < 2:
        return None

    action = segments[-1].lower()
    parent = segments[-2].lower()

    # Solo aceptamos verbos que indiquen creación.
    creation_prefixes = ("create", "add", "register")

    for prefix in creation_prefixes:
        if action.startswith(prefix) and len(action) > len(prefix):
            action_resource = singularize(action[len(prefix):])
            parent_resource = singularize(parent)

            # El nombre del recurso debe coincidir con el segmento anterior.
            if action_resource == parent_resource:
                return route

    return None


def singularize(word):
    """Convierte plurales ingleses comunes a singular."""
    word = word.lower()

    if word.endswith("ies"):
        return word[:-3] + "y"

    if word.endswith(("sses", "shes", "ches", "xes", "zes")):
        return word[:-2]

    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]

    return word


def _split_words(value):
    """Separa palabras en snake_case, camelCase y rutas."""
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return [
        word.lower()
        for word in re.findall(r"[a-zA-Z0-9]+", value)
        if word
    ]


def _param_resource_name(param):
    """Extrae el nombre del recurso de event_id, eventId, venue_id, etc."""
    name = param.lower()

    name = re.sub(r"(_id|id)$", "", name)

    return singularize(name) if name else None


def _resource_tokens(resource):
    """Obtiene los nombres posibles de un recurso creador.

    Ejemplo:
        /api/events/addevent -> {'event', 'events'}
        /api/venue/createvenue -> {'venue'}
    """
    tokens = set()

    for segment in resource.strip("/").split("/"):
        words = _split_words(segment)

        if not words:
            continue

        tokens.update(words)

        # addevent -> event
        # createvenue -> venue
        # getaccount -> account
        for word in words:
            for prefix in OPERATION_PREFIXES:
                if word.startswith(prefix) and len(word) > len(prefix):
                    remainder = word[len(prefix):]
                    tokens.add(remainder)
                    tokens.add(singularize(remainder))
                    break

    return {
        token
        for token in tokens
        if token not in {"api", "v1", "v2", "v3"}
    }


def _route_tokens(endpoint):
    """Extrae los posibles nombres de recurso de una ruta."""
    endpoint = PATH_PARAM.sub("", endpoint)

    tokens = set()

    for segment in endpoint.strip("/").split("/"):
        tokens.update(_resource_tokens(segment))

    return tokens


def resource_of_param(endpoint, param, resources=None):
    """Identifica el recurso al que pertenece un parámetro de ruta.

    Primero intenta identificarlo por el nombre del parámetro.
    Si no es posible (por ejemplo, {id}), compara los nombres presentes
    en la ruta con los recursos que crean los POST.

    Sin resources mantiene el comportamiento REST anterior.
    """

    if not resources:
        before = endpoint.split("{" + param + "}")[0]
        return before.rstrip("/")

    # 1. Intentar identificar el recurso mediante el nombre del parámetro.
    param_name = _param_resource_name(param)

    if param_name:
        matches = [
            resource
            for resource in resources
            if param_name in _resource_tokens(resource)
        ]

        if len(matches) == 1:
            return matches[0]

    # 2. Si el parámetro es genérico, comparar los nombres de las rutas.
    route_tokens = _route_tokens(endpoint)

    # Damos más importancia al último segmento de la ruta.
    route_without_param = PATH_PARAM.sub("", endpoint).rstrip("/")
    last_segment = route_without_param.split("/")[-1]
    last_tokens = _resource_tokens(last_segment)

    candidates = []

    for resource in resources:
        resource_tokens = _resource_tokens(resource)
        common = route_tokens & resource_tokens

        if not common:
            continue

        terminal_matches = last_tokens & resource_tokens

        # Primero gana el mayor número de coincidencias.
        # Después, la coincidencia con el último segmento.
        score = (len(common), len(terminal_matches))

        candidates.append((score, resource))

    if not candidates:
        return None

    best_score = max(score for score, _ in candidates)
    best_matches = [
        resource
        for score, resource in candidates
        if score == best_score
    ]

    # No adivinamos si dos recursos tienen exactamente la misma puntuación.
    if len(best_matches) != 1:
        return None

    return best_matches[0]


def deleted_resource(state, resources=None):
    """Identifica el recurso y el parámetro de una operación DELETE."""
    method, endpoint = state.split(" ", 1)

    if method != "DELETE":
        return None

    match = re.search(r"/\{([^{}]+)\}$", endpoint)

    if not match:
        return None

    param = match.group(1)

    resource = resource_of_param(endpoint, param, resources)

    if resource is None:
        return None

    return {
        "resource": resource,
        "param": param,
    }


def resource_of_field(field, resources):
    """Identifica el recurso asociado a un campo id del body."""
    base = re.sub(r"(_id|Id|ID)$", "", field).lower()

    if not base:
        return None

    for resource in sorted(resources):
        segment = resource.rstrip("/").split("/")[-1].lower()
        singular = singularize(segment)

        if base.endswith(singular):
            return resource

    return None


def build_correlation(model, bodies):
    """Calcula las relaciones entre recursos creados y sus identificadores.

    Returns:
        creates:
            POST que crean recursos.

        path_resources:
            Parámetros de ruta que pueden reutilizar IDs creados.

        body_resources:
            Campos ID de los cuerpos que pueden reutilizar IDs creados.

        deletes:
            Operaciones DELETE y sus recursos asociados.
    """

    # 1. Identificar las peticiones que crean recursos.
    creates = {}

    for state in model["states"]:
        resource = created_resource(state)

        if resource:
            creates[state] = resource

    resources = set(creates.values())

    # 2. Identificar los parámetros de ruta correlacionables.
    path_resources = {}

    for state in model["states"]:
        endpoint = state.split(" ", 1)[1]

        for param in PATH_PARAM.findall(endpoint):
            resource = resource_of_param(endpoint, param, resources)

            if resource:
                path_resources.setdefault(state, {})[param] = resource

    # 3. Correlacionar campos ID de los cuerpos.
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

    # 4. Identificar operaciones DELETE.
    deletes = {}

    for state in model["states"]:
        resource = deleted_resource(state, resources)

        if resource:
            deletes[state] = resource

    return {
        "creates": creates,
        "path_resources": path_resources,
        "body_resources": body_resources,
        "deletes": deletes,
    }
