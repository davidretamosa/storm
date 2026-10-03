"""Generación del plan de JMeter (.jmx) a partir del modelo de tráfico.

Cada iteración de un usuario virtual es una sesión que recorre la cadena de Markov:

    Thread Group
    ├── Flow Control Action "Nueva sesión" + JSR223 (elige la primera petición)
    └── While stormState != END
        ├── JSR223 Timer         (pausa observada antes de la petición)
        ├── JSR223 PostProcessor (tras cada petición, elige la siguiente)
        └── Switch stormIndex
            └── una petición HTTP por estado de la cadena

Al elegir cada petición, los scripts rellenan sus {parámetros} de ruta y su cuerpo
JSON con valores generados a partir de los observados (traffic_model/payloads.py).
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "templates"
PATH_PARAM = re.compile(r"\{(\w+)\}")


def _to_jmeter_path(endpoint: str) -> str:
    """'/api/accounts/{id}' -> '/api/accounts/${id}' (variable de JMeter)."""
    return PATH_PARAM.sub(r"${\1}", endpoint)


def build_samplers(states: List[str], bodies: Optional[dict] = None) -> List[dict]:
    """Una petición HTTP por estado, en el mismo orden que model['states'] (índice del Switch)."""
    bodies = bodies or {}
    samplers = []
    for state in states:
        method, endpoint = state.split(" ", 1)
        samplers.append({
            "name": state,
            "method": method,
            "path": _to_jmeter_path(endpoint),
            "params": PATH_PARAM.findall(endpoint),
            # Solo las peticiones con cuerpos observados envían ${stormBody}
            "has_body": state in bodies,
        })
    return samplers


def _groovy(script: str, model_json: str) -> str:
    """Script de JMeter: cabecera común con el modelo incrustado + la parte específica."""
    common = (TEMPLATES_DIR / "markov_common.groovy").read_text(encoding="utf-8")
    # El JSON va dentro de un string '''...''' de Groovy: hay que escapar las barras
    embedded = model_json.replace("\\", "\\\\").replace("'''", "\\'\\'\\'")
    return common.replace("__MODEL_JSON__", embedded) + (TEMPLATES_DIR / script).read_text(encoding="utf-8")


def generate_jmx(
    model: dict,
    think_times: Dict[str, Dict[str, List[int]]],
    profile: Dict[str, int],
    output_path: str,
    host: str = "localhost",
    port: int = 8080,
    path_params: Optional[dict] = None,
    bodies: Optional[dict] = None,
) -> None:
    """Escribe el .jmx.

    Al lanzar JMeter se pueden cambiar sin regenerar el plan: -Jhost= -Jport= (servidor)
    y -Jvusers= -Jrampup= -Jduration= (usuarios virtuales, rampa y duración en segundos).
    """
    path_params = path_params or {}
    bodies = bodies or {}
    samplers = build_samplers(model["states"], bodies)
    # Cada {param} de las rutas se declara como variable del plan (valor por defecto 1)
    path_variables = sorted({name for s in samplers for name in s["params"]})
    model_json = json.dumps(
        {**model, "think_time_ms": think_times, "path_params": path_params, "bodies": bodies},
        ensure_ascii=False,
        separators=(",", ":"),
    )

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    rendered = env.get_template("plan.jmx.j2").render(
        vusers=profile["vusers"],
        ramp_up=profile["ramp_up_seconds"],
        duration=profile["duration_seconds"],
        host=host,
        port=port,
        samplers=samplers,
        path_variables=path_variables,
        session_start_script=_groovy("session_start.groovy", model_json),
        next_request_script=_groovy("next_request.groovy", model_json),
    )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(rendered, encoding="utf-8")
