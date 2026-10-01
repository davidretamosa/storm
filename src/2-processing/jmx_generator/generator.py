"""Generación del plan de JMeter (.jmx) a partir del modelo de tráfico."""
import re
from pathlib import Path
from typing import Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).parent / "templates"
PATH_PARAM = re.compile(r"\{(\w+)\}")


def _to_jmeter_path(endpoint: str) -> str:
    """'/api/accounts/{id}' -> '/api/accounts/${id}' (variable de JMeter)."""
    return PATH_PARAM.sub(r"${\1}", endpoint)


def build_samplers(markov_matrix: Dict[str, Dict[str, float]], min_probability: float = 0.1) -> List[dict]:
    """Una petición HTTP por cada transición con probabilidad >= min_probability.

    TODO: de momento es una lista secuencial; falta que JMeter elija la siguiente
    petición según la probabilidad (p. ej. con Throughput Controllers).
    """
    samplers = []
    for source, targets in markov_matrix.items():
        for target, probability in targets.items():
            if probability < min_probability:
                continue
            method, endpoint = target.split(" ", 1)
            samplers.append({
                "name": f"{source} -> {target} ({probability:.0%})",
                "method": method,
                "path": _to_jmeter_path(endpoint),
                "params": PATH_PARAM.findall(endpoint),
            })
    return samplers


def generate_jmx(
    markov_matrix: Dict[str, Dict[str, float]],
    profile: Dict[str, int],
    output_path: str,
    host: str = "localhost",
    port: int = 8080,
    min_probability: float = 0.1,
) -> None:
    """Escribe el .jmx. host y port se pueden sobrescribir al lanzar JMeter (-Jhost= -Jport=)."""
    samplers = build_samplers(markov_matrix, min_probability)
    # Cada {param} de las rutas se declara como variable del plan (valor por defecto 1)
    path_variables = sorted({name for s in samplers for name in s["params"]})

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
    )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(rendered, encoding="utf-8")
