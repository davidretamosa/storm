"""Correlación: qué peticiones crean algo y qué ids pueden reutilizar lo creado."""
from traffic_model.correlation import build_correlation, created_resource, resource_of_field, resource_of_param

STATES = [
    "GET /api/accounts/{id}", "GET /api/transactions/{id}", "GET /api/users/{id}",
    "POST /api/accounts", "POST /api/accounts/{id}/deposit", "POST /api/transfers", "POST /api/users",
]
MODEL = {"states": STATES}
NUMBER = {"type": "number", "min": 1, "max": 100, "decimals": 2, "presence": 1.0}
ID = {"type": "choice", "values": [[1, 1.0]], "presence": 1.0}
BODIES = {
    "POST /api/accounts": {"userId": ID},
    "POST /api/transfers": {"fromAccountId": ID, "toAccountId": ID, "amount": NUMBER},
    "POST /api/users": {"id": ID, "name": ID},
}


def test_helpers():
    assert created_resource("POST /api/accounts") == "/api/accounts"
    assert created_resource("POST /api/accounts/{id}/deposit") is None   # actúa sobre algo, no crea
    assert created_resource("GET /api/accounts") is None
    assert resource_of_param("/api/accounts/{id}/deposit", "id") == "/api/accounts"
    resources = {"/api/accounts", "/api/users"}
    assert resource_of_field("userId", resources) == "/api/users"
    assert resource_of_field("fromAccountId", resources) == "/api/accounts"
    assert resource_of_field("id", resources) is None
    assert resource_of_field("productId", resources) is None


def test_build_correlation():
    corr = build_correlation(MODEL, BODIES)
    assert corr["creates"] == {
        "POST /api/accounts": "/api/accounts",
        "POST /api/transfers": "/api/transfers",
        "POST /api/users": "/api/users",
    }
    # /api/transactions no se crea con ningún POST: su {id} sigue saliendo de los logs
    assert corr["path_resources"] == {
        "GET /api/accounts/{id}": {"id": "/api/accounts"},
        "GET /api/users/{id}": {"id": "/api/users"},
        "POST /api/accounts/{id}/deposit": {"id": "/api/accounts"},
    }
    # En la transferencia solo la cuenta de origen es "mía"; la de destino es de otro
    assert corr["body_resources"] == {
        "POST /api/accounts": {"userId": "/api/users"},
        "POST /api/transfers": {"fromAccountId": "/api/accounts"},
    }
