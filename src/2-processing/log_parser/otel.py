"""Logs en formato OpenTelemetry (OTel): se pasan a las mismas columnas que el formato del proyecto.

parse_logs (parser.py) usa esta función con las líneas que tienen "attributes" (formato OTel);
las demás líneas se leen con el formato JSON acordado con input.
"""
import json
from datetime import datetime, timezone

def normalize_attributes(attributes):
    """Normaliza los atributos OpenTelemetry a un diccionario."""

    if isinstance(attributes, dict):
        return attributes

    if not isinstance(attributes, list):
        return {}

    result = {}

    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue

        key = attribute.get("key")
        value = attribute.get("value", {})

        if not key or not isinstance(value, dict):
            continue

        for value_type in (
            "stringValue",
            "intValue",
            "doubleValue",
            "boolValue",
        ):
            if value_type in value:
                result[key] = value[value_type]
                break

    return result

def parse_otel_record(record):
    """Un registro OTel (ya leído como diccionario) -> fila con nuestras columnas, o None si no vale."""
    attributes = normalize_attributes(record.get("attributes", {}))

    # 1. Método HTTP
    method = (
        attributes.get("http.request.method")
        or attributes.get("http.method")
        or record.get("method")
    )

    # 2. Ruta / Endpoint
    endpoint = (
        attributes.get("http.route")
        or attributes.get("url.path")
        or attributes.get("http.target")
        or record.get("endpoint")
    )

    if not method or not endpoint:
        return None

    row = {}

    # 3. Identificadores (acuerdo de proyecto + fallback estándar OTel)
    row["request_id"] = attributes.get("request.id") or record.get("spanId")
    # Una traza no equivale a una sesión de usuario.
    row["session_id"] = attributes.get("session.id")
    row["user_id"] = attributes.get("user.id")

    row["method"] = method
    row["endpoint"] = endpoint.split("?", 1)[0]

    # Ruta y parámetros de consulta
    path = attributes.get("url.path") or attributes.get("http.target") or endpoint
    query = attributes.get("url.query")

    # Compatibilidad con el formato antiguo de OpenTelemetry
    if "?" in path:
        path, legacy_query = path.split("?", 1)
        if query is None:
            query = legacy_query

    row["path"] = path
    row["query"] = query
    row["status"] = attributes.get("http.response.status_code") or attributes.get("http.status_code")
    row["duration_ms"] = attributes.get("app.request.duration_ms")
    row["request_size_bytes"] = attributes.get("app.request.size_bytes")
    row["response_size_bytes"] = attributes.get("app.response.size_bytes")

    # 4. Body (JSON): solo nos sirve si es un objeto
    row["body"] = None
    body = attributes.get("app.request.body") or attributes.get("http.request.body")
    if body:
        try:
            body = json.loads(body) if isinstance(body, str) else body
        except (ValueError, TypeError):
            body = None
        if isinstance(body, dict):
            row["body"] = body

    # 5. Timestamp (formato ISO8601 o nanosegundos Unix)
    row["timestamp"] = None
    raw_ts = record.get("timestamp") or record.get("Timestamp") or attributes.get("timestamp")
    if raw_ts:
        row["timestamp"] = str(raw_ts)
    else:
        nano_ts = (
            record.get("startTimeUnixNano")
            or record.get("TimestampUnixNano")
            or record.get("timeUnixNano")
        )
        if nano_ts:
            try:
                dt = datetime.fromtimestamp(int(nano_ts) / 1_000_000_000, tz=timezone.utc)
                row["timestamp"] = dt.isoformat()
            except (ValueError, OverflowError):
                row["timestamp"] = None

    if not row["timestamp"]:
        return None

    return row

def parse_otlp_export(record):
    """Extrae las peticiones HTTP de una exportación OTLP."""

    rows = []

    for resource in record.get("resourceSpans", []):
        for scope in resource.get("scopeSpans", []):
            for span in scope.get("spans", []):

                # Solo se procesan spans de servidor.
                if span.get("kind") not in (2, "SPAN_KIND_SERVER"):
                    continue

                row = parse_otel_record(span)

                if row is not None:
                    rows.append(row)

    return rows
