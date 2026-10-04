"""Orquestador de 2-processing: logs y/o .jar -> modelo de tráfico -> plan .jmx.

Uso (desde src/2-processing):
    python main.py --logs samples/access_sample.log                                  # solo logs
    python main.py --jar samples/demo-bankapp.jar                                    # solo .jar (app sin logs)
    python main.py --logs samples/access_sample.log --jar samples/demo-bankapp.jar   # combinado
    python main.py --logs logs/access.log --output output/plan.jmx --host bankapp --port 8080
"""
import argparse

import numpy as np

from jar_parser.parser import compare_with_logs, parse_jar
from jmx_generator.generator import generate_jmx
from log_parser.parser import parse_logs
from traffic_model.markov import build_markov_model
from traffic_model.payloads import build_body_models, build_path_params
from traffic_model.scaling import predict_traffic_scale
from traffic_model.think_time import add_default_pauses, build_think_times


def pause_range(text):
    """'1-3' (segundos) -> [1000, 1500, 2000, 2500, 3000] (milisegundos); '0-0' -> [0]."""
    low, high = (float(x) for x in text.split("-"))
    if low == high:
        return [int(low * 1000)]
    return [int(round(v)) for v in np.linspace(low * 1000, high * 1000, 5)]
    #dona 5 números repartits igualment entre low y high i després jmeter agafa un a latzar a cada pausa

def main() -> None:
    args = argparse.ArgumentParser(description="Genera un plan de JMeter a partir de logs y/o del .jar de la aplicación.")
    args.add_argument("--logs", help="access.log de la aplicación (cómo la usa la gente)")
    args.add_argument("--jar", help=".jar de la aplicación (qué endpoints y bodies existen)")
    args.add_argument("--output", default="output/generated_scenario.jmx", help="ruta del .jmx generado")
    args.add_argument("--host", default="localhost", help="host de la aplicación objetivo")
    args.add_argument("--port", type=int, default=8080, help="puerto de la aplicación objetivo")
    args.add_argument("--jar-weight", type=float, default=1,
                      help="cuánto pesa el .jar al mezclarlo con los logs: 1 = como una sesión más")
    args.add_argument("--default-pause", default="1-3",
                      help="pausa (s) cuando no hay datos en los logs, p. ej. 1-3; 0-0 = sin pausa")
    args.add_argument("--min-probability", type=float, default=0.0, help="descarta transiciones menos probables")
    args.add_argument("--max-steps", type=int, default=50, help="máximo de peticiones por sesión simulada")
    opts = args.parse_args()

    if not opts.logs and not opts.jar:
        args.error("hace falta --logs, --jar o los dos")

    print("--- 1. LECTURA ---")
    df_logs = None
    if opts.logs:
        df_logs = parse_logs(opts.logs)
        print(f"Logs: {len(df_logs)} peticiones, {df_logs['session_id'].nunique()} sesiones.")

    endpoints = None
    if opts.jar:
        endpoints = parse_jar(opts.jar)
        print(f".jar: {len(endpoints)} endpoints.")

    if df_logs is not None and endpoints is not None:
        coverage = compare_with_logs(endpoints, df_logs)
        for request in coverage["never_used"]:
            print(f"  - Nunca usado en los logs (se probará poco, por el .jar): {request}")
        for request in coverage["unknown"]:
            print(f"  - En los logs pero no en el .jar: {request}")

    print("--- 2. MODELADO DEL TRÁFICO ---")
    model = build_markov_model(df_logs, opts.min_probability, opts.max_steps,
                               endpoints=endpoints, jar_weight=opts.jar_weight)
    think_times = add_default_pauses(build_think_times(df_logs), model, pause_range(opts.default_pause))
    path_params = build_path_params(df_logs)
    bodies = build_body_models(df_logs, endpoints)
    profile = predict_traffic_scale(df_logs)
    print(f"{len(model['states'])} estados en la cadena de Markov; {profile['vusers']} usuarios virtuales.")
    print(f"{len(path_params)} peticiones con parámetros de ruta; {len(bodies)} con cuerpo JSON.")

    print("--- 3. GENERACIÓN DEL ESCENARIO ---")
    generate_jmx(model, think_times, profile, opts.output, opts.host, opts.port, path_params, bodies)
    print(f"Plan generado: {opts.output}")


if __name__ == "__main__":
    main()
