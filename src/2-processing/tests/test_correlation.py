"""Correlación: qué peticiones crean algo y qué ids pueden reutilizar lo creado."""
from traffic_model.correlation import (
    build_correlation,
    created_resource,
    resource_of_field,
    resource_of_param,
    deleted_resource,
)

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

def test_deleted_resource():
    # Detecta correctamente el recurso y su identificador
    assert deleted_resource("DELETE /api/accounts/{id}") == {
        "resource": "/api/accounts",
        "param": "id",
    }

    # El parámetro no tiene por qué llamarse id
    assert deleted_resource("DELETE /api/articles/{slug}") == {
        "resource": "/api/articles",
        "param": "slug",
    }


def test_deleted_resource_invalid():
    # No confunde otras operaciones con eliminaciones
    assert deleted_resource("GET /api/accounts/{id}") is None
    assert deleted_resource("POST /api/accounts") is None
    assert deleted_resource("PUT /api/accounts/{id}") is None

    # No identifica eliminaciones sin un parámetro final
    assert deleted_resource("DELETE /api/accounts") is None


def test_build_correlation_with_deletes():
    model = {
        "states": STATES + [
            "DELETE /api/accounts/{id}",
            "DELETE /api/users/{id}",
        ]
    }

    corr = build_correlation(model, BODIES)

    assert corr["deletes"] == {
        "DELETE /api/accounts/{id}": {
            "resource": "/api/accounts",
            "param": "id",
        },
        "DELETE /api/users/{id}": {
            "resource": "/api/users",
            "param": "id",
        },
    }