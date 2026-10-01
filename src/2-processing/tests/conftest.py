import pytest

LINES = [
    "2026-10-01T09:00:01.000+02:00 INFO  [r1] ACCESS - metodo=GET endpoint=/api/users/{id} ruta=/api/users/1 query=- estado=200 duracionMs=10 sesion=a",
    "2026-10-01T09:00:02.000+02:00 INFO  [r2] ACCESS - metodo=GET endpoint=/api/users/{id} ruta=/api/users/2 query=- estado=200 duracionMs=11 sesion=b",
    "2026-10-01T09:00:03.000+02:00 INFO  [r3] ACCESS - metodo=GET endpoint=/api/accounts/{id} ruta=/api/accounts/1 query=- estado=200 duracionMs=12 sesion=a",
    "2026-10-01T09:00:04.000+02:00 INFO  [r4] ACCESS - metodo=POST endpoint=/api/transfers ruta=/api/transfers query=- estado=201 duracionMs=40 sesion=b",
    "2026-10-01T09:00:05.000+02:00 INFO  [r5] ACCESS - metodo=POST endpoint=/api/transfers ruta=/api/transfers query=- estado=201 duracionMs=35 sesion=a",
    "2026-10-01T09:00:06.000+02:00 INFO  [-] Bankapp - Started BankappApplication in 2.1 seconds",
]


@pytest.fixture
def log_file(tmp_path):
    path = tmp_path / "access.log"
    path.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    return str(path)
