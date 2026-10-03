import json

import pytest


def request(time, request_id, session, method, endpoint, path, status, duration, body=None, user=None):
    """Una línea del log de la app del banco (JSON Lines)."""
    return json.dumps({
        "timestamp": f"2026-10-01T09:00:0{time}.000Z",
        "requestId": request_id,
        "sessionId": session,
        "userId": user,
        "method": method,
        "endpoint": endpoint,
        "path": path,
        "status": status,
        "durationMs": duration,
        "requestSizeBytes": 0,
        "responseSizeBytes": 100,
        "body": body,
    })


# Sesión a: users -> accounts -> transfers ; sesión b: users -> transfers
LINES = [
    request(1, "r1", "a", "GET", "/api/users/{id}", "/api/users/1", 200, 10, user=1),
    request(2, "r2", "b", "GET", "/api/users/{id}", "/api/users/2", 200, 11, user=2),
    request(3, "r3", "a", "GET", "/api/accounts/{id}", "/api/accounts/1", 200, 12, user=1),
    request(4, "r4", "b", "POST", "/api/transfers", "/api/transfers", 201, 40,
            body={"fromAccountId": 1, "amount": 10.5, "concept": "Cena con amigos"}, user=2),
    # body que no es un objeto JSON: se ignora
    request(5, "r5", "a", "POST", "/api/transfers", "/api/transfers", 201, 35, body="texto", user=1),
    # Líneas que no son peticiones válidas
    "2026-10-01 09:00:06 INFO Started BankappApplication in 2.1 seconds",
    "",
    json.dumps({"timestamp": "2026-10-01T09:00:07.000Z", "method": "GET"}),  # sin endpoint
]


@pytest.fixture
def log_file(tmp_path):
    path = tmp_path / "access.log"
    path.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    return str(path)
