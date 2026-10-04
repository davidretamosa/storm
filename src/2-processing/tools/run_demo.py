"""SOLO PARA LA DEMO: todo en un comando.

1. Genera el plan (main.py) con el log y el .jar de prueba.
2. Arranca el servidor de prueba (tools/demo_server.py), que hace de app del banco.
3. Lanza JMeter con el plan y enseña en directo las peticiones que llegan.
4. Cuando JMeter termina, para el servidor y enseña el resumen (% en el log vs % recibido).

Uso (desde src/2-processing):
    .venv/Scripts/python.exe tools/run_demo.py
    .venv/Scripts/python.exe tools/run_demo.py --vusers 20 --duration 120
"""
import argparse
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROCESSING = HERE.parent
sys.path.insert(0, str(PROCESSING))
sys.path.insert(0, str(HERE))

import demo_server  # noqa: E402
from jar_parser.parser import parse_jar  # noqa: E402
from log_parser.parser import parse_logs  # noqa: E402


def main():
    args = argparse.ArgumentParser(description="Demo completa en un comando.")
    args.add_argument("--logs", default="samples/access_sample.log")
    args.add_argument("--jar", default="samples/demo-bankapp.jar")
    args.add_argument("--jmeter", default="C:/jmeter/bin/jmeter.bat", help="ruta de jmeter.bat")
    args.add_argument("--vusers", type=int, default=10, help="usuarios virtuales")
    args.add_argument("--duration", type=int, default=60, help="segundos que dura la prueba")
    opts = args.parse_args()

    if not Path(opts.jmeter).exists():
        sys.exit(f"No encuentro JMeter en {opts.jmeter}. Pon su ruta con --jmeter")

    plan = PROCESSING / "output" / "demo_plan.jmx"

    print("=== 1. Generando el plan ===")
    subprocess.run([sys.executable, str(PROCESSING / "main.py"), "--logs", opts.logs, "--jar", opts.jar,
                    "--output", str(plan)], cwd=PROCESSING, check=True)

    print("\n=== 2. Arrancando el servidor de prueba (hace de app del banco) ===")
    df = parse_logs(PROCESSING / opts.logs)
    known = set(df["endpoint"]) | {e["endpoint"] for e in parse_jar(PROCESSING / opts.jar)}
    demo_server.Handler.endpoints = sorted(known, key=len, reverse=True)
    server = ThreadingHTTPServer(("127.0.0.1", 8080), demo_server.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print(f"\n=== 3. Lanzando JMeter: {opts.vusers} usuarios durante {opts.duration} s ===")
    print("    (cada línea [x.xs] es una petición que llega a la 'app')\n")
    subprocess.run([opts.jmeter, "-n", "-t", str(plan),
                    f"-Jvusers={opts.vusers}", f"-Jduration={opts.duration}", "-Jrampup=5",
                    "-j", str(PROCESSING / "output" / "jmeter.log")],
                   cwd=PROCESSING, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

    print("\n=== 4. Resultado ===")
    server.shutdown()
    server.server_close()
    demo_server.print_summary(df)


if __name__ == "__main__":
    main()
