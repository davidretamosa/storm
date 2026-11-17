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
from traffic_model.body_rules import (MIN_EXPECTED_MATCHES, MIN_UNIQUE_VALUES, bodies_by_request, different_pairs,
                                     expected_matches, hide_unique_values, is_number, learn_body_rules,
                                     numeric_quantiles, quantile_table, text_form, unique_fields)
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
    paths = [ROOT / "traffic_model" / "dto_bodies.py", ROOT / "traffic_model" / "body_rules.py"]
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


# ---------------------------------------------------------------------------
# Sección 3 · reglas (T-3.3): cuantiles, «distinto» y «único», aprendidos de las 2xx
# ---------------------------------------------------------------------------

ITEMS = "POST /items"
REFERENCE = Path(__file__).parents[1] / "bench/data/bankapp_vall_pic_3h.jsonl"   # solo lectura


def items(bodies, status=201):
    """DataFrame con un POST /items por body."""
    return frame([row(status, body, endpoint="/items") for body in bodies])


def never_equal(count):
    """`count` bodies con sourceId y targetId en {1, 2, 3}, nunca iguales (cada valor sale igual de a menudo)."""
    pairs = [(1, 2), (2, 3), (3, 1), (2, 1), (3, 2), (1, 3)]
    return [{"sourceId": pairs[i % 6][0], "targetId": pairs[i % 6][1]} for i in range(count)]


def test_quantile_table_goes_from_min_to_max():
    values = [7, 1.5, 3, 9.25, 4, 4, 2]
    table = quantile_table(values)
    assert len(table) == 21
    assert table == sorted(table)
    assert table[0] == 1.5 and table[-1] == 9.25
    precise = [1 / 3, 2 / 7, 5 / 9, 0.123456789]
    assert quantile_table(precise) == [round(float(q), 6) for q in np.quantile(precise, np.linspace(0, 1, 21))]
    assert quantile_table(precise)[10] == 0.309524            # mediana por interpolación lineal, 6 decimales


def test_quantiles_come_only_from_successful_requests():
    # Control positivo del filtro: los retiros con 400 de access_sample.log llevan los importes grandes
    df = parse_logs(LOG)
    rules = learn_body_rules(df, build_body_models(df, only_2xx=True))
    table = rules[WITHDRAW]["numbers"]["amount"]["q"]
    assert table[-1] == 188.05
    assert 4917.51 not in table


def test_quantiles_only_for_number_fields():
    bodies = [{"sourceId": i % 3 + 1, "size": i * 1.5, "mixed": i if i % 2 else "x"} for i in range(10)]
    fields = build_body_models(items(bodies))[ITEMS]
    assert fields["sourceId"]["type"] == "choice" and fields["mixed"]["type"] == "choice"
    result = numeric_quantiles(bodies, fields)
    assert list(result) == ["size"]
    assert result["size"]["decimals"] == fields["size"]["decimals"]
    assert is_number(3) and is_number(2.5) and not is_number(True) and not is_number("3")
    mixed = frame([row(201, {"a": 1}, endpoint="/items"), row(201, [1, 2], endpoint="/items"),
                   row(201, None, endpoint="/items"), row(201, "texto", endpoint="/other")])
    assert bodies_by_request(mixed) == {ITEMS: [{"a": 1}]}


def test_different_is_learned_when_chance_would_make_them_equal():
    bodies = never_equal(30)
    assert expected_matches([b["sourceId"] for b in bodies], [b["targetId"] for b in bodies]) == pytest.approx(10)
    assert different_pairs(bodies) == [["sourceId", "targetId"]]
    # Solo cuentan los bodies que llevan los dos campos con valor: dos null no son una coincidencia
    padded = bodies + [{"sourceId": None, "targetId": None}, {"sourceId": 1}, {"targetId": 1}]
    assert different_pairs(padded) == [["sourceId", "targetId"]]
    # true no es 1: no es una coincidencia
    assert different_pairs(bodies + [{"sourceId": True, "targetId": 1}]) == [["sourceId", "targetId"]]


def test_different_is_not_learned_when_they_sometimes_match():
    # Control negativo: los mismos bodies, con 2 iguales
    bodies = never_equal(30)
    bodies[0] = {"sourceId": 1, "targetId": 1}
    bodies[1] = {"sourceId": 2, "targetId": 2.0}     # 2 y 2.0 cuentan como iguales
    assert different_pairs(bodies) == []
    # Una sola coincidencia basta, y 2 y 2.0 son iguales
    once = never_equal(30)
    once[1] = {"sourceId": 2, "targetId": 2.0}
    assert different_pairs(once) == []


def test_different_needs_enough_evidence():
    bodies = never_equal(6)
    assert expected_matches([b["sourceId"] for b in bodies], [b["targetId"] for b in bodies]) < 5
    assert different_pairs(bodies) == []
    # El umbral es «al menos 5»: con 15 parejas uniformes en {1, 2, 3} se esperan 5, con 12 se esperan 4
    assert MIN_EXPECTED_MATCHES == 5
    cycle = [(1, 2), (2, 3), (3, 1)]
    five = [{"sourceId": cycle[i % 3][0], "targetId": cycle[i % 3][1]} for i in range(15)]
    four = five[:12]
    assert expected_matches([b["sourceId"] for b in five], [b["targetId"] for b in five]) == pytest.approx(5)
    assert different_pairs(five) == [["sourceId", "targetId"]]
    assert different_pairs(four) == []


def test_different_ignores_fields_that_never_share_values():
    bodies = [{"sourceId": 1 + i % 2, "targetId": 7 + i % 2} for i in range(30)]
    assert different_pairs(bodies) == []


def test_different_only_looks_at_id_fields():
    bodies = [{"size": b["sourceId"], "weight": b["targetId"]} for b in never_equal(30)]
    assert different_pairs(bodies) == []


def test_different_works_with_other_names():
    bodies = [{"srcId": b["sourceId"], "note": "x", "dstId": b["targetId"]} for b in never_equal(30)]
    assert different_pairs(bodies) == [["srcId", "dstId"]]


def test_unique_learns_the_form_without_copying_values():
    codes = [f"ref-{i:03d}k{i * 7 % 10}" for i in range(25)]
    df = items([{"code": code, "size": i} for i, code in enumerate(codes)])
    bodies = build_body_models(df)
    before = copy.deepcopy(bodies)
    rules = learn_body_rules(df, bodies)
    assert bodies == before                                  # learn_body_rules no cambia el modelo
    assert rules[ITEMS]["unique"] == {"code": {"prefix": "ref-0", "suffix": ""}}
    text = json.dumps(rules)
    assert not [code for code in codes if code in text]


def test_unique_needs_enough_values_and_no_repeats():
    assert MIN_UNIQUE_VALUES == 20

    def bodies(count):
        return [{"code": f"c{i}"} for i in range(count)]

    assert unique_fields(bodies(19)) == {}
    assert unique_fields(bodies(20)) == {"code": {"prefix": "c", "suffix": ""}}
    repeated = bodies(20)
    repeated[19] = {"code": "c0"}
    assert unique_fields(repeated) == {}
    empty = bodies(20)
    empty[5] = {"code": ""}
    assert unique_fields(empty) == {}
    # Se cuentan los valores del campo, no los bodies
    assert unique_fields(bodies(19) + [{"other": 1}] * 6) == {}


def test_unique_leaves_id_fields_alone():
    bodies = [{"sourceId": f"s-{i}", "code": f"c-{i}"} for i in range(25)]
    assert list(unique_fields(bodies)) == ["code"]


def test_text_form():
    assert text_form(["ana1@x.test", "pere7@x.test"]) == {"prefix": "storm-", "suffix": "@x.test"}
    assert text_form(["ref-001", "ref-002"]) == {"prefix": "ref-00", "suffix": ""}
    assert text_form(["${a}1", "${a}2"]) == {"prefix": "storm-", "suffix": ""}
    assert text_form(["a1${b}", "c2${b}"])["suffix"] == ""
    # Con @ en los textos pero no en el sufijo común, el sufijo queda vacío
    assert text_form(["a@x.test9", "b@y.test9"]) == {"prefix": "storm-", "suffix": ""}
    # El principio común es el de todos, aunque no vengan ordenados
    assert text_form(["ref-002", "abc", "ref-001"])["prefix"] == "storm-"
    # El sufijo no se solapa con el prefijo
    assert text_form(["ab", "abab"]) == {"prefix": "ab", "suffix": ""}
    assert text_form(["x${a}1", "x${a}2"])["prefix"] == "storm-"


def test_dto_unique_forms_join_the_rules():
    form = {"prefix": "storm.", "suffix": "@example.com", "max": 40}
    bodies = {"POST /signup": {"contact": {"type": "choice", "values": [["storm.storm@example.com", 1.0]],
                                           "presence": 1.0}}}
    dto_unique = {"POST /signup": {"contact": form}, "POST /missing": {"contact": form}}
    rules = learn_body_rules(None, bodies, dto_unique)
    assert rules == {"POST /signup": {"numbers": {}, "different": [], "unique": {"contact": form}}}
    # Sin log, y con un log sin ningún body de esa petición, lo mismo
    assert learn_body_rules(items(never_equal(2)), bodies, dto_unique)["POST /signup"] == rules["POST /signup"]
    rules["POST /signup"]["unique"]["contact"]["max"] = 5
    assert form["max"] == 40                                 # las reglas llevan una copia de la forma
    # Si el log ya enseña que un campo es único, manda la forma del log
    codes = frame([row(201, {"code": f"ref-{i:02d}"}, endpoint="/signup") for i in range(20)])
    joined = learn_body_rules(codes, build_body_models(codes), {"POST /signup": {"code": form}})
    assert joined["POST /signup"]["unique"] == {"code": {"prefix": "ref-", "suffix": ""}}


def test_rules_with_jmeter_expressions_are_dropped():
    bodies = [{"a${x}Id": b["sourceId"], "targetId": b["targetId"]} for b in never_equal(30)]
    clean = [{"sourceId": b["sourceId"], "targetId": b["targetId"]} for b in never_equal(30)]
    df = frame([row(201, body, endpoint="/items") for body in bodies]
               + [row(201, body, endpoint="/other") for body in clean])
    assert different_pairs(bodies) == [["a${x}Id", "targetId"]]
    rules = learn_body_rules(df, build_body_models(df))
    assert ITEMS not in rules
    assert rules["POST /other"]["different"] == [["sourceId", "targetId"]]
    # También con el ${ en un campo numérico o en un campo único, y en las formas del DTO (el filtro va al final)
    tricky = frame([row(201, {"s${x}": i * 1.5}, endpoint="/numbers") for i in range(5)]
                   + [row(201, {"n${x}": f"t{i}"}, endpoint="/texts") for i in range(25)])
    assert learn_body_rules(tricky, build_body_models(tricky)) == {}
    form = {"prefix": "ref-", "suffix": ""}
    assert learn_body_rules(None, {"POST /x": {"c": {}}}, {"POST /x": {"c${x}": form}}) == {}


def test_hide_unique_values():
    form = {"prefix": "ref-", "suffix": ""}
    size = {"type": "number", "min": 1, "max": 9, "decimals": 0, "presence": 1.0}
    bodies = {ITEMS: {"code": {"type": "choice", "values": [["ref-1", 0.5], ["ref-2", 0.5]], "presence": 0.8},
                      "size": dict(size)}}
    rules = {ITEMS: {"numbers": {}, "different": [], "unique": {"code": form, "absent": form}},
             "POST /missing": {"numbers": {}, "different": [], "unique": {"code": form}}}
    hide_unique_values(bodies, rules)
    assert bodies == {ITEMS: {"code": {"type": "choice", "values": [[fixed_value(form), 1.0]], "presence": 0.8},
                              "size": size}}


def test_rules_on_the_reference_log():
    df = parse_logs(str(REFERENCE))
    bodies = build_body_models(df, only_2xx=True)
    before = copy.deepcopy(bodies)
    rules = learn_body_rules(df, bodies)
    assert bodies == before                                  # learn_body_rules no cambia el modelo

    transfers = rules["POST /api/transfers"]
    assert {tuple(sorted(pair)) for pair in transfers["different"]} == {("fromAccountId", "toAccountId")}
    rows = [b for b in df[df["endpoint"] == "/api/transfers"]["body"] if isinstance(b, dict)]
    assert expected_matches([b["fromAccountId"] for b in rows], [b["toAccountId"] for b in rows]) > 100

    ranges = {request: (rule["numbers"]["amount"]["q"][0], rule["numbers"]["amount"]["q"][-1])
              for request, rule in rules.items()}
    assert ranges == {"POST /api/accounts/{id}/deposit": (5.70, 493.08),
                      "POST /api/accounts/{id}/withdraw": (5.06, 39.99),
                      "POST /api/transfers": (5.33, 49.90)}
    assert not any(rule["unique"] for rule in rules.values())
    for request in ("POST /api/users", "POST /api/accounts", "POST /api/sessions"):
        assert bodies[request] == {} and request not in rules


def write_log(path, bodies, endpoint="/items"):
    """Un log JSON Lines con un POST 201 por body, en 5 sesiones."""
    lines = []
    for i, body in enumerate(bodies):
        lines.append(json.dumps({"timestamp": f"2026-10-01T09:{i // 60:02d}:{i % 60:02d}.000Z",
                                 "requestId": f"r{i}", "sessionId": f"s{i % 5}", "userId": 1, "method": "POST",
                                 "endpoint": endpoint, "path": endpoint, "status": 201, "durationMs": 5,
                                 "body": body}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_unique_log_values_do_not_reach_the_plan(tmp_path):
    codes = [f"lot-{i:03d}z{i * 3 % 7}" for i in range(25)]
    log = write_log(tmp_path / "items.jsonl", [{"code": code} for code in codes])
    off = markov_script(generate(["--logs", str(log)], tmp_path / "off.jmx"))
    on = markov_script(generate(["--logs", str(log), "--realistic-bodies"], tmp_path / "on.jmx"))
    assert all(code in off for code in codes)
    assert not [code for code in codes if code in on]
    assert fixed_value({"prefix": "lot-0", "suffix": ""}) in on


def run_main(args, output):
    """La salida estándar de `python main.py <args> --output <output>` (PYTHONHASHSEED=0)."""
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    command = [sys.executable, "main.py", *args, "--output", str(output)]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_main_prints_the_rules_only_with_the_flag(tmp_path):
    on = run_main(["--logs", LOG, "--realistic-bodies"], tmp_path / "on.jmx")
    off = run_main(["--logs", LOG], tmp_path / "off.jmx")
    assert "Bodies realistas: reglas en" in on
    assert "Bodies realistas: reglas en" not in off
    # Dos peticiones: /items con cuantiles y un campo único; /pairs con cuantiles y dos campos distintos
    unique = write_log(tmp_path / "unique.jsonl", [{"code": f"c{i}", "size": i} for i in range(25)])
    pairs = write_log(tmp_path / "pairs.jsonl", [{"sourceId": 1 + i % 2, "targetId": 2 - i % 2, "size": i}
                                                 for i in range(25)], endpoint="/pairs")
    log = tmp_path / "both.jsonl"
    log.write_text(unique.read_text(encoding="utf-8") + pairs.read_text(encoding="utf-8"), encoding="utf-8")
    counts = run_main(["--logs", str(log), "--realistic-bodies"], tmp_path / "both.jmx")
    assert ("Bodies realistas: reglas en 2 peticiones (2 con cuantiles, 1 con campos distintos, "
            "1 con campos únicos).") in counts
