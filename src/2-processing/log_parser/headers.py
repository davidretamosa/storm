"""Normalización y filtrado de cabeceras HTTP."""

import re



EXCLUDED_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "host",
    "content-length",
    "content-type",
    "connection",
    "transfer-encoding",
    "keep-alive",
    "upgrade",
    "te",
    "trailer",
}

SENSITIVE_PATTERN = re.compile(
    r"token|secret|password|api[-_]?key|credential",
    re.IGNORECASE,
)


def normalize_headers(headers):
    """Normaliza las cabeceras y excluye valores no reproducibles."""

    if not isinstance(headers, dict):
        return {}

    result = {}

    for name, values in headers.items():

        if not isinstance(name, str):
            continue

        name = name.strip().lower()

        if not name:
            continue

        if name in EXCLUDED_HEADERS:
            continue

        if SENSITIVE_PATTERN.search(name):
            continue

        if not isinstance(values, list):
            values = [values]

        valid_values = [
            value for value in values
            if isinstance(value, str)
            and "\r" not in value
            and "\n" not in value
        ]

        if valid_values:
            result[name] = valid_values

    return result