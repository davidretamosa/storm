"""Inicio de sesión: para apps que piden "identificarse" antes de usarlas (como la del banco).

La app del banco funciona así:
    POST /api/sessions {"userId": 1}  ->  {"sessionId": "abc123", ...}
    y TODAS las demás peticiones llevan la cabecera  X-Session-Id: abc123  (si no, 400)

Con --session (y --session-endpoint si la ruta no es /api/sessions), el plan de JMeter hace ese POST al empezar cada sesión simulada,
guarda el sessionId de la respuesta y lo pone en la cabecera de todas las peticiones.
Las peticiones de sesiones (/api/sessions...) se quitan del modelo: las hace JMeter él solo,
al principio, y no deben salir al azar en medio (p. ej. cerrar la sesión a mitad).
"""
from traffic_model.payloads import distribution

# Cómo se llama cada cosa en la app del banco (si otra app usa otros nombres, se cambian aquí)
HEADER = "X-Session-Id"       # cabecera que lleva la sesión en cada petición
USER_FIELD = "userId"         # campo del body del POST que inicia la sesión
ID_FIELD = "sessionId"        # campo de la respuesta con el identificador de la sesión


def is_session_request(endpoint, session_endpoint):
    """'/api/sessions' y '/api/sessions/{id}' son peticiones de sesión."""
    return endpoint == session_endpoint or endpoint.startswith(session_endpoint + "/")


def remove_session_requests(df, endpoints, session_endpoint):
    """Quita las peticiones de sesión de los logs (tabla) y del .jar (lista de endpoints)."""
    if df is not None and not df.empty:
        keep = []
        for endpoint in df["endpoint"]:
            keep.append(not is_session_request(endpoint, session_endpoint))
        df = df[keep]
    if endpoints:
        kept = []
        for e in endpoints:
            if not is_session_request(e["endpoint"], session_endpoint):
                kept.append(e)
        endpoints = kept
    return df, endpoints


def build_session_config(session_endpoint, df=None, users=None):
    """Qué necesita JMeter para iniciar sesión:

    {"endpoint": "/api/sessions", "header": "X-Session-Id", "user_field": "userId",
     "id_field": "sessionId", "users": [[1, 0.5], [2, 0.5]]}

    users = con qué usuarios se inicia sesión (tienen que existir en la app):
    - los que se pasen con --session-users (p. ej. 1,2,3), si se pasan;
    - si no, los userId que aparecen en los logs, con su frecuencia;
    - si no hay, el 1.
    """
    if users:
        user_values = users
    elif df is not None and "user_id" in df.columns and df["user_id"].notna().any():
        user_values = [int(u) for u in df["user_id"].dropna()]
    else:
        user_values = [1]

    return {
        "endpoint": session_endpoint,
        "header": HEADER,
        "user_field": USER_FIELD,
        "id_field": ID_FIELD,
        "users": distribution(user_values),
    }
