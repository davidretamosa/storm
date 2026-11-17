"""Generación del plan de JMeter (.jmx) a partir del modelo de tráfico."""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "templates"
PATH_PARAM = re.compile(r"\{(\w+)\}")
BODY_RULES_PLACEHOLDER = "__BODY_RULES_JSON__"


def _to_jmeter_path(endpoint: str) -> str:
    """Convierte los parámetros de ruta en variables de JMeter."""
    return PATH_PARAM.sub(r"${\1}", endpoint)


def build_samplers(
    states: List[str],
    bodies: Optional[dict] = None
) -> List[dict]:
    """Una petición HTTP por estado de la cadena de Markov."""

    bodies = bodies or {}
    samplers = []

    for state in states:
        method, endpoint = state.split(" ", 1)

        samplers.append({
            "name": state,
            "method": method,
            "path": _to_jmeter_path(endpoint),
            "params": PATH_PARAM.findall(endpoint),
            "has_body": state in bodies,
        })

    return samplers


def _groovy(script: str, model_json: str) -> str:
    """Script de JMeter con el modelo incrustado."""

    common = (
        TEMPLATES_DIR / "markov_common.groovy"
    ).read_text(encoding="utf-8")

    embedded = model_json.replace(
        "\\", "\\\\"
    ).replace("'''", "\\'\\'\\'")

    return common.replace(
        "__MODEL_JSON__", embedded
    ) + (TEMPLATES_DIR / script).read_text(encoding="utf-8")


def _body_fix_script(rules: dict) -> str:
    """PreProcessor de la capa de IA (--realistic-bodies) con las reglas de los bodies incrustadas.

    Las reglas se escapan igual que el modelo en _groovy, para que el Groovy las lea tal cual.
    """

    rules_json = json.dumps(
        rules, ensure_ascii=False, separators=(",", ":")
    )

    embedded = rules_json.replace(
        "\\", "\\\\"
    ).replace("'''", "\\'\\'\\'")

    return (
        TEMPLATES_DIR / "body_fix.groovy"
    ).read_text(encoding="utf-8").replace(
        BODY_RULES_PLACEHOLDER, embedded
    )


def generate_jmx(
    model: dict,
    think_times: Dict[str, Dict[str, List[int]]],
    profile: Dict[str, int],
    output_path: str,
    host: str = "localhost",
    port: int = 8080,
    path_params: Optional[dict] = None,
    bodies: Optional[dict] = None,
    correlation: Optional[dict] = None,
    session: Optional[dict] = None,
    query_params: Optional[dict] = None,
    header_models: Optional[dict] = None,
    body_rules: Optional[dict] = None,
) -> None:
    """Escribe el plan JMX generado."""

    path_params = path_params or {}
    bodies = bodies or {}
    correlation = correlation or {}

    samplers = build_samplers(model["states"], bodies)

    path_variables = sorted({
        name
        for s in samplers
        for name in s["params"]
    })

    model_json = json.dumps(
        {
            **model,
            "think_time_ms": think_times,
            "path_params": path_params,
            "query_params": query_params or {},
            "header_models": header_models or {},
            "bodies": bodies,
            "correlation": correlation,
            "session": session,
        },
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
        request_headers_script=(
            TEMPLATES_DIR / "request_headers.groovy"
        ).read_text(encoding="utf-8"),
        session_start_script=_groovy(
            "session_start.groovy", model_json
        ),
        next_request_script=_groovy(
            "next_request.groovy", model_json
        ),
        session=session,
        login_response_script=_groovy(
            "login_response.groovy", model_json
        ) if session else "",
        body_fix_script=_body_fix_script(
            body_rules
        ) if body_rules else "",
    )

    Path(output_path).parent.mkdir(
        parents=True, exist_ok=True
    )

    Path(output_path).write_text(
        rendered, encoding="utf-8"
    )

    Path(output_path).parent.mkdir(
        parents=True, exist_ok=True
    )

    Path(output_path).write_text(
        rendered, encoding="utf-8"
    )