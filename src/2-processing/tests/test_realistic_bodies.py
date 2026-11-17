"""Tests del flag --realistic-bodies (capa de IA, cadena T-3).

Cada subparte de la cadena añade aquí su sección.
"""
import copy
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from jar_parser.class_file import Reader, read_constant_pool, read_element_value
from jar_parser.parser import parse_jar, read_jar_classes
from log_parser.parser import COLUMNS, parse_logs
from traffic_model.dto_bodies import (add_dto_bodies, dto_body, fixed_value, number_range, text_model,
                                      unique_names)
from traffic_model.payloads import build_body_models
from traffic_model.status_filter import successful_rows

ROOT = Path(__file__).resolve().parents[1]   # src/2-processing
LOG = "samples/access_sample.log"
JAR = "samples/demo-bankapp.jar"
WITHDRAW = "POST /api/accounts/{id}/withdraw"


def frame(rows):
    """DataFrame con las columnas de parse_logs; cada fila es un dict con las columnas que hagan falta."""
    return pd.DataFrame(rows, columns=list(COLUMNS.values()))


def row(status, body, method="POST", endpoint="/api/transfers"):
    return {"method": method, "endpoint": endpoint, "path": endpoint, "status": status, "body": body}


# ---------------------------------------------------------------------------
# Sección 1 · 2xx (T-3.1): el modelo de los bodies sale solo de las peticiones 2xx
# ---------------------------------------------------------------------------

# El filtro compartido con el T-1.2: tiene que ser este texto, byte a byte
STATUS_FILTER_TEXT = '''"""Filtro de peticiones por código de respuesta HTTP."""


def successful_rows(df):
    """Filas que la aplicación aceptó (2xx) y filas sin código de respuesta.

    Si el log no tiene la columna `status`, o la tiene vacía, lo devuelve tal cual.
    """
    if df is None or df.empty or "status" not in df.columns or df["status"].isna().all():
        return df
    status = df["status"]
    return df[status.isna() | ((status >= 200) & (status < 300))]
'''


def test_successful_rows_keeps_2xx_and_rows_without_status():
    df = frame([row(s, {"a": 1}) for s in (200, 201, 299, 300, 400, 500, np.nan)])
    kept = successful_rows(df)["status"].tolist()
    assert kept[:3] == [200, 201, 299]
    assert len(kept) == 4 and pd.isna(kept[3])


def test_successful_rows_returns_the_same_object_without_status():
    empty = frame([])
    no_column = pd.DataFrame([{"method": "POST", "endpoint": "/x", "body": {"a": 1}}])
    all_nan = frame([row(np.nan, {"a": 1}), row(np.nan, {"a": 2})])
    assert successful_rows(None) is None
    for df in (empty, no_column, all_nan):
        assert successful_rows(df) is df


def test_status_filter_is_the_shared_file():
    path = ROOT / "traffic_model" / "status_filter.py"
    expected = hashlib.sha256(STATUS_FILTER_TEXT.encode("utf-8")).hexdigest()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_only_2xx_narrows_the_numeric_range():
    # Control positivo: en access_sample.log, 3 de los 9 retiros son 400 y llevan los importes grandes
    bodies = build_body_models(parse_logs(LOG), only_2xx=True)
    assert bodies[WITHDRAW]["amount"]["max"] == 188.05


def test_without_only_2xx_the_range_is_the_team_one():
    # Control negativo: sin el parámetro, el modelo de siempre (todas las filas)
    df = parse_logs(LOG)
    default = build_body_models(df)
    off = build_body_models(df, only_2xx=False)
    assert default[WITHDRAW]["amount"]["max"] == 4917.51
    assert default == off


def test_a_request_with_only_failed_bodies_keeps_its_model():
    df = frame([
        row(201, {"amount": 10}),
        row(400, {"code": "x"}, endpoint="/api/loans"),
        row(400, {"code": "y"}, endpoint="/api/loans"),
    ])
    with_flag = build_body_models(df, only_2xx=True)
    assert with_flag["POST /api/loans"] == build_body_models(df)["POST /api/loans"]


def test_empty_successes_and_failed_bodies_keep_the_full_model():
    # Las 2xx solo llevan {}: el modelo es el de todas las filas, no {}
    df = frame([row(201, {}), row(201, {}), row(400, {"amount": 5000}), row(400, {"amount": 7000})])
    with_flag = build_body_models(df, only_2xx=True)
    assert with_flag == build_body_models(df)
    assert with_flag["POST /api/transfers"] != {}


def test_the_set_of_requests_with_body_does_not_change():
    df = parse_logs(LOG)
    endpoints = parse_jar(JAR)
    on = build_body_models(df, endpoints, only_2xx=True)
    off = build_body_models(df, endpoints, only_2xx=False)
    assert set(on) == set(off)
    # Sin el .jar también: el DTO no puede tapar una petición que se haya perdido por el filtro
    assert set(build_body_models(df, only_2xx=True)) == set(build_body_models(df))


def test_presence_comes_from_the_2xx_bodies():
    df = frame([
        row(201, {"amount": 10, "concept": "luz"}),
        row(201, {"amount": 20}),
        row(400, {"amount": 9000}),
        row(400, {"amount": 9500}),
    ])
    fields = build_body_models(df, only_2xx=True)["POST /api/transfers"]
    assert fields["concept"]["presence"] == 0.5
    assert fields["amount"]["max"] == 20


def test_reference_log_does_not_change():
    # En el log de referencia todas las peticiones son 2xx: por eso el banco no puede enseñar esta subparte
    log = Path(__file__).parents[1] / "bench/data/bankapp_vall_pic_3h.jsonl"
    df = parse_logs(str(log))
    assert build_body_models(df, only_2xx=True) == build_body_models(df)


def markov_script(plan):
    """El script del JSR223PostProcessor «Elegir siguiente petición (Markov)», ya sin escapes XML."""
    tree = ET.parse(plan)
    for node in tree.iter("JSR223PostProcessor"):
        if node.get("testname") == "Elegir siguiente petición (Markov)":
            for prop in node.iter("stringProp"):
                if prop.get("name") == "script":
                    return prop.text
    raise AssertionError("no está el script de Markov en el plan")


def generate(args, output):
    """`python main.py <args> --output <output>` en un subproceso con PYTHONHASHSEED=0 (como bench/tests)."""
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    command = [sys.executable, "main.py", *args, "--output", str(output)]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return output


def test_main_with_the_flag_uses_the_2xx_model(tmp_path):
    off = markov_script(generate(["--logs", LOG], tmp_path / "off.jmx"))
    on = markov_script(generate(["--logs", LOG, "--realistic-bodies"], tmp_path / "on.jmx"))
    # El modelo va en compacto (separators=(",", ":")), como lo escribe generator.py
    assert '"max":4917.51' in off
    assert '"max":188.05' in on
    assert "4917.51" not in on


# ---------------------------------------------------------------------------
# Sección 2 · DTO (T-3.2): las peticiones sin campos en los logs salen del DTO del .jar
# ---------------------------------------------------------------------------

FIXTURE_JAR = ROOT / "tests" / "data" / "bodies_fixture.jar"
SIGNUP = "POST /signup"
SIGNUP_ENDPOINT = {"method": "POST", "endpoint": "/signup",
                   "body": {"type": "com.example.SignupForm", "fields": {"handle": "String"}}}

# Los términos de la app del banco que no pueden salir en los módulos nuevos, y las excepciones exactas
APP_TERMS = ("account", "transfer", "iban", "deposit", "withdraw", "bankapp", "balance", "saldo",
             "cuenta", "ingreso", "amount", "concept", "email", "user")
ALLOWED = ("@Email", '"Email"', "EMAIL_PREFIX", "EMAIL_SUFFIX", "vusers")


@pytest.fixture
def classes():
    return read_jar_classes(str(FIXTURE_JAR))


def field_annotations(classes, class_name, field_name):
    """{nombre corto: valores} de las anotaciones de un campo."""
    for field in classes[class_name]["fields"]:
        if field["name"] == field_name:
            return {a["type"].split(".")[-1]: a["values"] for a in field["annotations"]}
    raise AssertionError(f"no está el campo {field_name}")


def made(simple_name, **values):
    """Una anotación de validación hecha a mano, como las que lee class_file.py."""
    return {"type": "jakarta.validation.constraints." + simple_name, "values": values}


def text_of(fields, name):
    return fields[name]["values"][0][0]


def app_terms(paths):
    """[(archivo, línea, término)] de los términos de la app del banco que salen en `paths`."""
    found = []
    for path in paths:
        for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
            for allowed in ALLOWED:
                line = line.replace(allowed, "")
            lower = line.lower()
            for term in APP_TERMS:
                if term in lower:
                    found.append((str(path), number, term))
    return found


def test_read_class_keeps_field_annotations(classes):
    annotations = field_annotations(classes, "com.example.SignupForm", "handle")
    assert "NotBlank" in annotations
    assert annotations["Size"] == {"min": 3, "max": 12}


def test_long_and_double_annotation_values_are_read(classes):
    # @Min y @Max guardan un long: antes class_file.py lo leía como None
    annotations = field_annotations(classes, "com.example.SignupForm", "rooms")
    assert annotations["Min"] == {"value": 2}
    assert annotations["Max"] == {"value": 9}
    # El .jar de prueba no lleva ningún double ni float: un constant pool hecho a mano con los tres
    pool_bytes = (struct.pack(">H", 6)                       # 5 posiciones (Long y Double ocupan dos)
                  + struct.pack(">Bf", 4, 1.5)               # 1: Float
                  + struct.pack(">Bq", 5, -9000000000)       # 2-3: Long
                  + struct.pack(">Bd", 6, 0.5))              # 4-5: Double
    pool = read_constant_pool(Reader(pool_bytes))
    assert pool[1] == 1.5 and pool[2] == -9000000000 and pool[4] == 0.5
    assert read_element_value(Reader(b"D" + struct.pack(">H", 4)), pool) == 0.5
    assert read_element_value(Reader(b"F" + struct.pack(">H", 1)), pool) == 1.5


def test_parse_jar_bodies_do_not_carry_annotations():
    # La salida de parse_jar no cambia: los campos de un body siguen siendo nombre -> tipo
    bodies = [e["body"] for e in parse_jar(JAR) if e["body"]]
    assert bodies
    for body in bodies:
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in body["fields"].items())


def test_dto_body_respects_the_validations(classes):
    # Control positivo: cada validación del DTO de prueba se respeta
    fields, unique = dto_body(classes, "com.example.SignupForm", unique_names(classes))
    assert "id" not in fields and "KIND" not in fields and "tags" not in fields
    assert text_of(fields, "handle") == "storm-handle"
    assert len(text_of(fields, "motto")) >= 20
    assert len(text_of(fields, "slogan")) >= 40
    assert len(text_of(fields, "nick")) <= 8
    assert text_of(fields, "contact") == "storm.storm@example.com"
    ranges = {name: [fields[name]["min"], fields[name]["max"]]
              for name in ("fee", "seats", "floor500", "tiny", "rooms")}
    assert ranges == {"fee": [1, 9.99], "seats": [1, 100], "floor500": [500, 599],
                      "tiny": [0.01, 0.5], "rooms": [2, 9]}
    assert fields["groupId"]["values"] == [[1, 1.0]]
    assert set(unique) == {"contact", "slogan", "nick"}


def test_number_range_moves_when_the_default_does_not_fit():
    model = {"type": "number", "min": 1, "max": 100, "decimals": 2, "presence": 1.0}

    def bounds(*annotations):
        result = number_range(model, list(annotations))
        return [result["min"], result["max"]]

    assert bounds(made("DecimalMin", value="500")) == [500, 599]                         # (a)
    assert bounds(made("DecimalMax", value="0.5")) == [0.5, 0.5]                         # (b)
    assert bounds(made("Positive"), made("DecimalMax", value="0.5")) == [0.01, 0.5]      # (c)
    assert bounds(made("DecimalMin", value="10"), made("DecimalMax", value="5")) == [10, 10]  # (d)
    # (c) con el mínimo anotado por encima del rango por defecto, y los dos límites de @Min/@Max
    assert bounds(made("Min", value=500), made("Max", value=1000)) == [500, 1000]
    assert bounds(made("DecimalMin", value="20"), made("Min", value=30)) == [30, 100]
    assert bounds(made("PositiveOrZero"), made("DecimalMax", value="-1")) == [0, 0]       # (d)
    assert bounds({"type": "javax.validation.constraints.DecimalMax", "values": {"value": "50"}}) == [1, 50]
    # Los límites se redondean hacia dentro: nunca un valor que la validación rechaza
    assert bounds(made("DecimalMax", value="99.999")) == [1, 99.99]
    assert bounds(made("DecimalMin", value="500.001")) == [500.01, 599]
    whole = {**model, "decimals": 0}
    assert number_range(whole, [made("DecimalMax", value="9.5")])["max"] == 9
    assert number_range(whole, [made("DecimalMin", value="2.5")])["min"] == 3
    assert number_range(whole, [made("DecimalMax", value="10", inclusive=0)])["max"] == 9
    assert bounds(made("DecimalMax", value="0.57")) == [0.57, 0.57]                      # sin ruido binario
    assert bounds(made("DecimalMin", value="0.000000001"), made("DecimalMax", value="5")) == [1, 5]
    # Ningún valor con esos decimales cabe: con solo máximo, el máximo; con mínimo, el mínimo
    assert number_range(whole, [made("DecimalMax", value="0.5")])["max"] == 0
    assert number_range(whole, [made("DecimalMax", value="0.5")])["min"] == 0
    assert bounds(made("DecimalMin", value="0.001"), made("DecimalMax", value="0.009")) == [0.01, 0.01]
    # Un valor que no es un número no dice nada
    assert bounds(made("DecimalMin", value="NaN"), made("Min", value=5)) == [5, 100]
    assert bounds(made("DecimalMin", value="Infinity")) == [1, 100]
    assert bounds(made("DecimalMin", value="abc")) == [1, 100]
    assert bounds(made("DecimalMin", value=True)) == [1, 100]
    assert number_range(whole, [made("Min", value=9223372036854775807)])["min"] == 9223372036854775807


def test_email_respects_size():
    value, form = text_model("contact", [made("Email"), made("Size", max=16)])
    assert len(value) <= 16
    assert value.endswith("@example.com")
    assert form["max"] == 16
    # Ni siquiera el sufijo cabe: se corta hasta el máximo
    assert len(text_model("contact", [made("Email"), made("Size", max=5)])[0]) == 5
    # Con máximo se conserva middle y se acorta antes el prefijo (decidido por la central, noche)
    assert fixed_value({"prefix": "storm.", "suffix": "@example.com", "max": 20}) == "stostorm@example.com"
    # Con mínimo, se rellena con "x" justo después del prefijo
    assert fixed_value({"prefix": "storm.", "suffix": "@example.com", "min": 30}) == \
        "storm." + "x" * 7 + "storm@example.com"


def test_unique_comes_from_the_entity(classes):
    # Draft lleva @Column(unique = true) en "handle", pero no es una @Entity
    assert unique_names(classes) == {"contact", "slogan", "nick"}


def test_dto_never_makes_an_id_unique():
    column = {"type": "javax.persistence.Column", "values": {"unique": 1}}      # también javax.*
    entity = {"type": "javax.persistence.Entity", "values": {}}
    handmade = {
        "com.example.Item": {"name": "com.example.Item", "annotations": [entity],
                             "fields": [{"name": "sourceId", "type": "java.lang.String", "static": False,
                                         "annotations": [column]}]},
        "com.example.ItemForm": {"name": "com.example.ItemForm", "annotations": [],
                                 "fields": [{"name": "sourceId", "type": "java.lang.String", "static": False,
                                             "annotations": []}]},
    }
    unique = unique_names(handmade)
    assert unique == {"sourceId"}
    fields, forms = dto_body(handmade, "com.example.ItemForm", unique)
    assert "sourceId" in fields
    assert forms == {}


def test_empty_log_bodies_are_built_from_the_dto(classes):
    df = frame([row(201, {}, endpoint="/signup") for _ in range(3)])
    bodies = build_body_models(df, only_2xx=True)
    assert bodies[SIGNUP] == {}
    # La petición sale dos veces (manda la primera) y hay otra que no lleva body (no se le añade)
    draft = {"method": "POST", "endpoint": "/signup", "body": {"type": "com.example.Draft", "fields": {}}}
    other = {"method": "POST", "endpoint": "/other", "body": {"type": "com.example.SignupForm", "fields": {}}}
    replaced, forms = add_dto_bodies(bodies, df, [SIGNUP_ENDPOINT, draft, other], classes)
    assert replaced == [SIGNUP]
    assert text_of(bodies[SIGNUP], "handle") == "storm-handle"
    assert "contact" in bodies[SIGNUP]
    assert "POST /other" not in bodies
    # Las formas son lo que reciben el T-3.3 y el T-3.4
    assert forms[SIGNUP] == {"contact": {"prefix": "storm.", "suffix": "@example.com"},
                             "slogan": {"prefix": "storm-slogan-", "suffix": "", "min": 40},
                             "nick": {"prefix": "storm-nick-", "suffix": "", "max": 8}}


def test_jar_only_requests_get_the_dto_model(classes):
    bodies = build_body_models(None, [SIGNUP_ENDPOINT], only_2xx=True)
    assert text_of(bodies[SIGNUP], "handle") == "test"        # el de add_bodies_from_dto
    alpha = {"method": "POST", "endpoint": "/alpha", "body": {"type": "com.example.SignupForm",
                                                              "fields": {"handle": "String"}}}
    bodies = build_body_models(None, [SIGNUP_ENDPOINT, alpha], only_2xx=True)
    replaced, _ = add_dto_bodies(bodies, None, [SIGNUP_ENDPOINT, alpha], classes)
    assert replaced == ["POST /alpha", SIGNUP]                # ordenadas
    assert text_of(bodies[SIGNUP], "handle") == "storm-handle"


def test_the_dto_never_replaces_what_the_log_teaches(classes):
    # Control negativo: si el log enseña campos, mandan los logs
    df = frame([row(201, {"handle": "abc"}, endpoint="/signup"), row(201, {}, endpoint="/signup")])
    bodies = build_body_models(df, only_2xx=True)
    before = copy.deepcopy(bodies)
    assert add_dto_bodies(bodies, df, [SIGNUP_ENDPOINT], classes) == ([], {})
    assert bodies == before


def test_failed_bodies_with_fields_also_block_the_dto(classes):
    df = frame([row(201, {}, endpoint="/signup"), row(400, {"handle": "x"}, endpoint="/signup")])
    bodies = build_body_models(df, only_2xx=True)
    before = copy.deepcopy(bodies)
    assert add_dto_bodies(bodies, df, [SIGNUP_ENDPOINT], classes) == ([], {})
    assert bodies == before


def test_without_endpoints_or_classes_nothing_changes(classes):
    df = frame([row(201, {}, endpoint="/signup")])
    for endpoints, jar_classes in (([], classes), (None, classes), ([SIGNUP_ENDPOINT], {})):
        bodies = build_body_models(df, only_2xx=True)
        before = copy.deepcopy(bodies)
        assert add_dto_bodies(bodies, df, endpoints, jar_classes) == ([], {})
        assert bodies == before
    # Un DTO sin ningún campo que se sepa generar tampoco cambia nada
    only_lists = {"com.example.Bag": {"name": "com.example.Bag", "annotations": [], "fields": [
        {"name": "tags", "type": "java.util.List", "static": False, "annotations": []},
        {"name": "id", "type": "java.lang.Long", "static": False,
         "annotations": [{"type": "com.fasterxml.jackson.annotation.JsonProperty",
                          "values": {"access": "READ_ONLY"}}]}]}}
    bag = {"method": "POST", "endpoint": "/signup", "body": {"type": "com.example.Bag", "fields": {"id": "Long"}}}
    bodies = build_body_models(None, [bag], only_2xx=True)
    before = copy.deepcopy(bodies)
    assert add_dto_bodies(bodies, None, [bag], only_lists) == ([], {})
    assert bodies == before


def test_dto_values_are_synthetic(classes):
    unique = unique_names(classes)
    for class_name in classes:
        built = dto_body(classes, class_name, unique)
        for model in built[0].values():
            for value, _ in model.get("values", []):
                if isinstance(value, str):
                    assert value.startswith("storm-") or re.fullmatch(r"storm\..*@example\.com", value), value


def test_new_modules_know_nothing_of_the_bankapp():
    # El T-3.3 y el T-3.4 añaden aquí sus archivos
    paths = [ROOT / "traffic_model" / "dto_bodies.py"]
    assert app_terms(paths) == []


def test_the_search_finds_what_it_looks_for(tmp_path):
    # Control negativo del anterior: la búsqueda encuentra lo que busca y respeta las excepciones
    upper = tmp_path / "upper.py"
    upper.write_text("ACCOUNT = 1\n", encoding="utf-8")
    lower = tmp_path / "lower.py"
    lower.write_text("email = 2\n", encoding="utf-8")
    allowed = tmp_path / "allowed.py"
    allowed.write_text('x = validation(a, "Email")\n', encoding="utf-8")
    assert [term for _, _, term in app_terms([upper, lower])] == ["account", "email"]
    assert app_terms([allowed]) == []


def plan_model(plan):
    """El modelo (JSON) que va dentro del script de Markov del plan."""
    script = markov_script(plan)
    start = script.index("parseText('''") + len("parseText('''")
    return json.loads(script[start:script.index("''')", start)])


def test_main_with_the_flag_and_the_jar(tmp_path):
    on = plan_model(generate(["--jar", JAR, "--realistic-bodies"], tmp_path / "on.jmx"))
    off = plan_model(generate(["--jar", JAR], tmp_path / "off.jmx"))
    generate(["--logs", LOG, "--jar", JAR, "--realistic-bodies"], tmp_path / "logs.jmx")
    assert on["bodies"]["POST /api/users"]["name"]["values"] == [["storm-name", 1.0]]
    assert off["bodies"]["POST /api/users"]["name"]["values"] == [["test", 1.0]]
    # El body del DTO entra antes de la correlación: el log de referencia guarda las altas con {}, y con
    # el flag el userId del DTO se liga a lo que crea la sesión
    reference = str(Path(__file__).parents[1] / "bench/data/bankapp_vall_pic_3h.jsonl")
    linked = plan_model(generate(["--logs", reference, "--session", "--jar", JAR, "--realistic-bodies"],
                                 tmp_path / "linked.jmx"))
    assert linked["correlation"]["body_resources"]["POST /api/accounts"]["userId"] == "/api/users"
