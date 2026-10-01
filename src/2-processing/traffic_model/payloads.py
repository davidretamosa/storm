"""Datos de las peticiones: valores de los parámetros de ruta y cuerpos JSON observados.

Todo se guarda como distribuciones (listas [valor, probabilidad]) para que JMeter
genere peticiones parecidas a las reales en vez de repetir siempre la misma.
"""
import json
import re
from collections import Counter
from decimal import Decimal
from typing import Dict, List, Optional

import pandas as pd

PATH_PARAM = re.compile(r"\{(\w+)\}")
# Campos que parecen identificadores: se toman de los valores vistos, no de un rango,
# para no inventar ids que no existen en la aplicación
ID_FIELD = re.compile(r"(^id$|Id$|_id$)")
MAX_VALUES = 50


def _distribution(values) -> List[list]:
    """[[valor, probabilidad], ...] con los MAX_VALUES valores más frecuentes."""
    # Se cuenta por su JSON para admitir objetos y listas (no son hashables).
    # JMeter sustituye ${...} en los scripts: esos valores no se pueden incrustar
    keys = (json.dumps(v, sort_keys=True, ensure_ascii=False) for v in values)
    counts = Counter(k for k in keys if "${" not in k)
    top = counts.most_common(MAX_VALUES)
    total = sum(n for _, n in top)
    return [[json.loads(key), n / total] for key, n in top]


def _template_regex(endpoint: str) -> re.Pattern:
    """'/api/accounts/{id}/deposit' -> regex que captura id en '/api/accounts/3/deposit'."""
    parts = re.split(r"(\{\w+\})", endpoint)
    pattern = "".join(
        f"(?P<{part[1:-1]}>[^/]+)" if PATH_PARAM.fullmatch(part) else re.escape(part)
        for part in parts
    )
    return re.compile(f"^{pattern}$")


def build_path_params(df: pd.DataFrame) -> Dict[str, Dict[str, List[list]]]:
    """Por cada petición con {parámetros}, los valores vistos en 'ruta' y su frecuencia.

    Un parámetro sin valores observados queda como lista vacía (JMeter usará 1).
    """
    result: Dict[str, Dict[str, List[list]]] = {}
    for (method, endpoint), group in df.groupby(["method", "endpoint"]):
        params = PATH_PARAM.findall(endpoint)
        if not params:
            continue
        regex = _template_regex(endpoint)
        matches = [regex.match(p) for p in group["path"].dropna()]
        matches = [m for m in matches if m]
        result[f"{method} {endpoint}"] = {
            name: _distribution(m[name] for m in matches) for name in params
        }
    return result


def _decimals(value: float) -> int:
    exponent = Decimal(str(value)).as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _field_model(name: str, values: list, presence: float) -> dict:
    numbers = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if numbers and len(numbers) == len(values) and not ID_FIELD.search(name):
        return {
            "type": "number",
            "min": min(numbers),
            "max": max(numbers),
            "decimals": min(2, max(_decimals(v) for v in numbers)),
            "presence": presence,
        }
    return {"type": "choice", "values": _distribution(values), "presence": presence}


def _parse_json(body: str) -> Optional[dict]:
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def build_body_models(df: pd.DataFrame) -> Dict[str, Dict[str, dict]]:
    """Por cada petición con cuerpo JSON, un modelo por campo:

    - number: valor aleatorio entre el mínimo y el máximo observados (importes, cantidades).
    - choice: uno de los valores observados según su frecuencia (textos, ids, objetos).
    - presence: proporción de cuerpos en los que aparece el campo.
    """
    result: Dict[str, Dict[str, dict]] = {}
    with_body = df.dropna(subset=["body"]) if "body" in df else df.iloc[0:0]
    for (method, endpoint), group in with_body.groupby(["method", "endpoint"]):
        bodies = [b for b in map(_parse_json, group["body"]) if b is not None]
        if not bodies:
            continue
        fields: Dict[str, list] = {}
        for body in bodies:
            for name, value in body.items():
                fields.setdefault(name, []).append(value)
        result[f"{method} {endpoint}"] = {
            name: _field_model(name, values, len(values) / len(bodies))
            for name, values in fields.items()
        }
    return result
