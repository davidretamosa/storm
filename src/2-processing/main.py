"""Orquestador de 2-processing: logs (+ .jar) -> modelo de tráfico -> plan .jmx.

Uso (desde src/2-processing):
    python main.py samples/access_sample.log
    python main.py logs/access.log --output output/plan.jmx --host bankapp --port 8080
"""
import argparse

from jmx_generator.generator import generate_jmx
from log_parser.parser import parse_logs
from traffic_model.markov import build_markov_model
from traffic_model.payloads import build_body_models, build_path_params
from traffic_model.scaling import predict_traffic_scale
from traffic_model.think_time import build_think_times


def main() -> None:
    args = argparse.ArgumentParser(description="Genera un plan de JMeter a partir de logs de acceso.")
    args.add_argument("log_file", help="access.log de la aplicación objetivo")
    args.add_argument("--output", default="output/generated_scenario.jmx", help="ruta del .jmx generado")
    args.add_argument("--host", default="localhost", help="host de la aplicación objetivo")
    args.add_argument("--port", type=int, default=8080, help="puerto de la aplicación objetivo")
    args.add_argument("--min-probability", type=float, default=0.0, help="descarta transiciones menos probables")
    args.add_argument("--max-steps", type=int, default=50, help="máximo de peticiones por sesión simulada")
    opts = args.parse_args()

    print("--- 1. PARSING ---")
    df_logs = parse_logs(opts.log_file)
    print(f"{len(df_logs)} peticiones, {df_logs['session_id'].nunique()} sesiones.")
    # TODO: jar_parser (endpoints declarados en el .jar)

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
