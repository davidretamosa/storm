"""Aprendizaje de las cabeceras HTTP observadas en los logs."""

from log_parser.headers import normalize_headers
from traffic_model.payloads import distribution


def build_header_models(df, allowed_headers=None):
    """Aprende las combinaciones de cabeceras por petición."""

    result = {}

    if df is None or df.empty or "headers" not in df.columns:
        return result

    allowed = {
        name.strip().lower()
        for name in (allowed_headers or [])
    }

    if not allowed:
        return result

    for (method, endpoint), group in df.groupby(
        ["method", "endpoint"]
    ):
        combinations = []

        for headers in group["headers"]:
            normalized = normalize_headers(headers)

            filtered = {
                name: values
                for name, values in normalized.items()
                if name in allowed
            }

            combinations.append(filtered)

        if any(combinations):
            request = method + " " + endpoint
            result[request] = distribution(combinations)

    return result