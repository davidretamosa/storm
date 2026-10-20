"""Servidor eco: tools/demo_server.py tal qual + un registre del trànsit rebut en el format de log del projecte.

    python -m ai.bench.echo_server --out rebut.jsonl  <els arguments de tools/demo_server.py>

Cada petició rebuda és una línia JSON com les del log de la bankapp (timestamp, requestId, sessionId,
method, endpoint, path, status, durationMs, mides, body), que `parse_logs` torna a llegir.

sessionId: la capçalera X-Storm-Bench, si el pla està instrumentat (vegeu run.instrument), que identifica
cada sessió de JMeter (fil + iteració); si no, X-Session-Id; si no, null.
"""
import argparse
import io
import json
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import demo_server  # noqa: E402

BENCH_HEADER = "X-Storm-Bench"
_write_lock = threading.Lock()


class EchoHandler(demo_server.Handler):
    out = None  # fitxer obert on s'escriu el trànsit

    def handle_request(self):
        self._started = time.time()
        length = int(self.headers.get("Content-Length") or 0)
        self._raw_body = self.rfile.read(length) if length else b""
        self.rfile = io.BytesIO(self._raw_body)   # el demo_server el torna a llegir
        super().handle_request()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = handle_request

    def reply(self, status, response):
        super().reply(status, response)
        self.record(status, response)

    def record(self, status, response):
        try:
            body = json.loads(self._raw_body) if self._raw_body else None
        except ValueError:
            body = None
        line = {
            "timestamp": datetime.fromtimestamp(self._started, timezone.utc).isoformat(timespec="milliseconds")
                         .replace("+00:00", "Z"),
            "requestId": str(uuid.uuid4()),
            "sessionId": self.headers.get(BENCH_HEADER) or self.headers.get("X-Session-Id"),
            "userId": None,
            "method": self.command,
            "endpoint": demo_server.to_endpoint(self.path, self.endpoints),
            "path": self.path,
            "status": status,
            "durationMs": round((time.time() - self._started) * 1000),
            "requestSizeBytes": len(self._raw_body),
            "responseSizeBytes": len(response),
            "body": body if isinstance(body, dict) else None,
            "appSessionId": self.headers.get("X-Session-Id"),
        }
        with _write_lock:
            self.out.write(json.dumps(line, ensure_ascii=False) + "\n")
            self.out.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--out", required=True)
    opts, rest = parser.parse_known_args(argv)
    with open(opts.out, "w", encoding="utf-8") as out:
        EchoHandler.out = out
        demo_server.Handler = EchoHandler   # el main() del demo_server fa servir aquest nom
        sys.argv = ["demo_server.py", *rest]
        demo_server.main()


if __name__ == "__main__":
    main()
