"""Orquestador de 2-processing: logs (+ .jar) -> modelo de tráfico -> plan .jmx.

Uso (desde src/2-processing):
    python main.py samples/access_sample.log
    python main.py samples/access_sample.log --jar samples/demo-bankapp.jar
    python main.py logs/access.log --output output/plan.jmx --host bankapp --port 8080
"""
import argparse

from jar_parser.parser import compare_with_logs, parse_jar
from jmx_generator.generator import generate_jmx
from log_parser.parser import parse_logs
from traffic_model.markov import build_markov_model
from traffic_model.payloads import build_body_models, build_path_params
from traffic_model.scaling import predict_traffic_scale
from traffic_model.think_time import build_think_times


def main() -> None:
    args = argparse.ArgumentParser(description="Genera un plan de JMeter a partir de logs de acceso.")
    args.add_argument("log_file", help="access.log de la aplicación objetivo")
    args.add_argument("--jar", help="(opcional) .jar de la aplicación, para descubrir todos sus endpoints")
    args.add_argument("--output", default="output/generated_scenario.jmx", help="ruta del .jmx generado")
    args.add_argument("--host", default="localhost", help="host de la aplicación objetivo")
    args.add_argument("--port", type=int, default=8080, help="puerto de la aplicación objetivo")
    args.add_argument("--min-probability", type=float, default=0.0, help="descarta transiciones menos probables")
    args.add_argument("--max-steps", type=int, default=50, help="máximo de peticiones por sesión simulada")
    opts = args.parse_args()

    print("--- 1. PARSING ---")
    df_logs = parse_logs(opts.log_file)
    print(f"{len(df_logs)} peticiones, {df_logs['session_id'].nunique()} sesiones.")

    # Opcional: la API completa a partir del .jar. De momento solo se informa;
    # el modelo sigue saliendo solo de los logs (ver README, "jar_parser").
    if opts.jar:
        endpoints = parse_jar(opts.jar)
        coverage = compare_with_logs(endpoints, df_logs)
        print(f"{len(endpoints)} endpoints en el .jar.")
        for request in coverage["never_used"]:
            print(f"  - Nunca usado en los logs (no se probará): {request}")
        for request in coverage["unknown"]:
            print(f"  - En los logs pero no en el .jar: {request}")

    print("--- 2. MODELADO DEL TRÁFICO ---")
    model = build_markov_model(df_logs, opts.min_probability, opts.max_steps)
    think_times = build_think_times(df_logs)
    path_params = build_path_params(df_logs)
    bodies = build_body_models(df_logs)
    profile = predict_traffic_scale(df_logs)
    print(f"{len(model['states'])} estados en la cadena de Markov; {profile['vusers']} usuarios virtuales.")
    print(f"{len(path_params)} peticiones con parámetros de ruta; {len(bodies)} con cuerpo JSON.")

    print("--- 3. GENERACIÓN DEL ESCENARIO ---")
    generate_jmx(model, think_times, profile, opts.output, opts.host, opts.port, path_params, bodies)
    print(f"Plan generado: {opts.output}")


if __name__ == "__main__":
    main()
