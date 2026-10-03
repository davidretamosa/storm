"""SOLO PARA LA DEMO: servidor de prueba que hace de "app del banco" para recibir el tráfico de JMeter.

No es la app real: responde a todo con un JSON vacío (GET -> 200, POST -> 201). Sirve para:
  1. Ver en directo cada petición que envía JMeter (con su pausa, sus ids y su body).
  2. Al parar (Ctrl+C), comparar el % de cada petición recibida con el % que había en el log:
     si el modelo funciona, deben parecerse.

Uso (desde src/2-processing):
    .venv/Scripts/python.exe tools/demo_server.py --log samples/access_sample.log
    .venv/Scripts/python.exe tools/demo_server.py --stop-after 70     (se para solo a los 70 s)
Y en otra terminal, JMeter contra http://localhost:8080 (ver DEMO.md).
"""
import argparse
import json
import re
import sys
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Para importar log_parser al ejecutarlo como script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from log_parser.parser import parse_logs  # noqa: E402

received = Counter()
lock = threading.Lock()
start_time = time.time()


def to_endpoint(path, endpoints):
    """'/api/accounts/3/deposit' -> '/api/accounts/{id}/deposit' (usando los endpoints del log)."""
    path = path.split("?")[0]
    for endpoint in endpoints:
        pattern = "^" + re.sub(r"\\\{\w+\\\}", "[^/]+", re.escape(endpoint)) + "$"
        if re.match(pattern, path):
            return endpoint
    return path


class Handler(BaseHTTPRequestHandler):
    endpoints = []

    def handle_request(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:  # para que se vean los acentos: {"name":"Laura Martí"} -> {"name":"Laura Martí"}
            body = json.dumps(json.loads(body), ensure_ascii=False)
        except ValueError:
            pass
        key = self.command + " " + to_endpoint(self.path, self.endpoints)
        with lock:  # varios usuarios a la vez: una línea cada vez para que no se mezclen
            received[key] += 1
            total = sum(received.values())
            seconds = time.time() - start_time
            print(f"[{seconds:6.1f}s] #{total:<4} {self.command:6} {self.path:32} {body}", flush=True)

        status = 201 if self.command == "POST" else 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = handle_request

    def log_message(self, *args):
        pass  # sin el log por defecto de http.server


def print_summary(df):
    """Tabla: % de cada petición en el log vs % recibido de JMeter."""
    in_log = (df["method"] + " " + df["endpoint"]).value_counts(normalize=True)
    total = sum(received.values())
    print("\n" + "=" * 78)
    print(f"RESUMEN: {total} peticiones recibidas de JMeter")
    print("=" * 78)
    print(f"{'Petición':48} {'% en el log':>12} {'% recibido':>12}")
    for key in sorted(set(in_log.index) | set(received)):
        log_pct = in_log.get(key, 0) * 100
        received_pct = received[key] / total * 100 if total else 0
        print(f"{key:48} {log_pct:11.1f}% {received_pct:11.1f}%")


def main():
    args = argparse.ArgumentParser(description="Servidor de prueba para la demo (hace de app del banco).")
    args.add_argument("--log", default="samples/access_sample.log", help="log con el que se generó el .jmx")
    args.add_argument("--port", type=int, default=8080)
    args.add_argument("--stop-after", type=int, help="parar solo tras estos segundos (si no, Ctrl+C)")
    opts = args.parse_args()

    df = parse_logs(opts.log)
    # Los más largos primero, para que /api/accounts/{id}/deposit no se confunda con /api/accounts/{id}
    Handler.endpoints = sorted(set(df["endpoint"]), key=len, reverse=True)

    server = ThreadingHTTPServer(("127.0.0.1", opts.port), Handler)
    print(f"Servidor de prueba escuchando en http://localhost:{opts.port}  (Ctrl+C para parar y ver el resumen)")
    if opts.stop_after:
        threading.Timer(opts.stop_after, server.shutdown).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print_summary(df)


if __name__ == "__main__":
    main()
