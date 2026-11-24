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



def test_resource_of_param_with_verb_based_routes():
    resources = {
        "/api/events/addevent",
        "/api/venue/createvenue",
        "/api/category/createcategory",
    }

    assert resource_of_param(
        "/api/events/getevent/{event_id}",
        "event_id",
        resources,
    ) == "/api/events/addevent"

    assert resource_of_param(
        "/api/events/getevent/{eventId}",
        "eventId",
        resources,
    ) == "/api/events/addevent"

    assert resource_of_param(
        "/api/venue/getvenue/{venue_id}",
        "venue_id",
        resources,
    ) == "/api/venue/createvenue"

    assert resource_of_param(
        "/api/category/getcategory/{category_id}",
        "category_id",
        resources,
    ) == "/api/category/createcategory"


def test_resource_of_param_with_generic_id():
    resources = {
        "/api/events/addevent",
        "/api/venue/createvenue",
        "/api/category/createcategory",
    }

    assert resource_of_param(
        "/api/events/getevent/{id}",
        "id",
        resources,
    ) == "/api/events/addevent"

    assert resource_of_param(
        "/api/venue/getvenue/{id}",
        "id",
        resources,
    ) == "/api/venue/createvenue"


def test_build_correlation_with_verb_based_routes():
    model = {
        "states": [
            "POST /api/events/addevent",
            "GET /api/events/getevent/{event_id}",
            "GET /api/events/getevent/{eventId}",
            "DELETE /api/events/deleteevent/{event_id}",
            "POST /api/venue/createvenue",
            "GET /api/venue/getvenue/{venue_id}",
            "POST /api/category/createcategory",
            "GET /api/category/getcategory/{category_id}",
        ]
    }

    correlation = build_correlation(model, {})

    assert correlation["path_resources"] == {
        "GET /api/events/getevent/{event_id}": {
            "event_id": "/api/events/addevent"
        },
        "GET /api/events/getevent/{eventId}": {
            "eventId": "/api/events/addevent"
        },
        "DELETE /api/events/deleteevent/{event_id}": {
            "event_id": "/api/events/addevent"
        },
        "GET /api/venue/getvenue/{venue_id}": {
            "venue_id": "/api/venue/createvenue"
        },
        "GET /api/category/getcategory/{category_id}": {
            "category_id": "/api/category/createcategory"
        },
    }

    assert correlation["deletes"] == {
        "DELETE /api/events/deleteevent/{event_id}": {
            "resource": "/api/events/addevent",
            "param": "event_id",
        }
    }


def test_resource_of_param_does_not_guess_ambiguous_resources():
    resources = {
        "/api/events/addevent",
        "/api/events/addother",
    }

    assert resource_of_param(
        "/api/events/getsomething/{id}",
        "id",
        resources,
    ) is None

def test_created_resource_with_parent_id():
    # Crea un recurso aunque la ruta también reciba un ID.
    assert created_resource(
        "POST /api/attendees/addattendee/{eventId}"
    ) == "/api/attendees/addattendee"

    # No debe confundir operaciones con creaciones.
    assert created_resource(
        "POST /api/accounts/{id}/deposit"
    ) is None

    # Tampoco debe confundir rutas cuyo nombre no coincide.
    assert created_resource(
        "POST /api/events/addattendee/{eventId}"
    ) is None


def test_build_correlation_with_attendee_creation():
    model = {
        "states": [
            "POST /api/events/addevent",
            "POST /api/attendees/addattendee/{eventId}",
            "GET /api/events/getevent/{id}",
            "GET /api/attendees/getattendee/{id}",
            "DELETE /api/attendees/deleteattendee/{id}",
        ]
    }

    correlation = build_correlation(model, {})

    assert correlation["creates"] == {
        "POST /api/events/addevent": "/api/events/addevent",
        "POST /api/attendees/addattendee/{eventId}":
            "/api/attendees/addattendee",
    }

    assert correlation["path_resources"] == {
        "POST /api/attendees/addattendee/{eventId}": {
            "eventId": "/api/events/addevent"
        },
        "GET /api/events/getevent/{id}": {
            "id": "/api/events/addevent"
        },
        "GET /api/attendees/getattendee/{id}": {
            "id": "/api/attendees/addattendee"
        },
        "DELETE /api/attendees/deleteattendee/{id}": {
            "id": "/api/attendees/addattendee"
        },
    }

    assert correlation["deletes"] == {
        "DELETE /api/attendees/deleteattendee/{id}": {
            "resource": "/api/attendees/addattendee",
            "param": "id",
        }
    }


# --- No enviar el propio id al crear, y avisar de la cobertura ---
from traffic_model.correlation import strip_own_ids, unlinked_params


def test_strip_own_ids_from_create_bodies():
    f = {"type": "choice", "values": [[1, 1.0]], "presence": 1.0}
    states = ["POST /api/visits", "POST /api/events/addevent", "POST /api/transfers"]
    bodies = {
        "POST /api/visits": {"id": f, "petId": f, "description": f},
        "POST /api/events/addevent": {"event_id": f, "eventTitle": f},
        "POST /api/transfers": {"fromAccountId": f},
    }
    corr = build_correlation({"states": states}, bodies)
    cleaned = strip_own_ids(bodies, corr)
    assert set(cleaned["POST /api/visits"]) == {"petId", "description"}      # petId es de OTRO recurso: se queda
    assert set(cleaned["POST /api/events/addevent"]) == {"eventTitle"}
    assert set(cleaned["POST /api/transfers"]) == {"fromAccountId"}


def test_unlinked_params_reports_uncovered_requests():
    states = ["POST /api/owners", "GET /api/owners/{ownerId}", "GET /api/stats/{year}"]
    corr = build_correlation({"states": states}, {})
    assert unlinked_params({"states": states}, corr, {}) == ["GET /api/stats/{year}"]
    # Si los logs traen valores para el parámetro, sí se puede probar
    assert unlinked_params({"states": states}, corr, {"GET /api/stats/{year}": {"year": [["2025", 1.0]]}}) == []


def test_named_params_are_not_guessed_from_the_rest_of_the_route():
    """PetClinic: en /owners/{ownerId}/pets/{petId}/visits, ownerId y petId se enlazaban al id de las visitas."""
    states = [
        "POST /api/owners", "POST /api/visits", "GET /api/owners/{ownerId}",
        "POST /api/owners/{ownerId}/pets/{petId}/visits", "GET /api/pettypes/{petTypeId}", "POST /api/pettypes",
        "GET /api/specialties/{specialtyId}", "POST /api/specialties",
    ]
    corr = build_correlation({"states": states}, {})
    pr = corr["path_resources"]
    assert pr["POST /api/owners/{ownerId}/pets/{petId}/visits"] == {"ownerId": "/api/owners"}   # petId: nadie crea mascotas
    assert pr["GET /api/owners/{ownerId}"] == {"ownerId": "/api/owners"}
    assert pr["GET /api/pettypes/{petTypeId}"] == {"petTypeId": "/api/pettypes"}
    assert pr["GET /api/specialties/{specialtyId}"] == {"specialtyId": "/api/specialties"}


def test_generic_id_is_still_resolved_by_the_route():
    states = ["POST /api/accounts", "GET /api/accounts/{id}", "POST /api/transfers", "GET /api/transfers/{id}"]
    pr = build_correlation({"states": states}, {})["path_resources"]
    assert pr["GET /api/accounts/{id}"] == {"id": "/api/accounts"}
    assert pr["GET /api/transfers/{id}"] == {"id": "/api/transfers"}
