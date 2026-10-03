import zipfile

import pandas as pd

from jar_parser.class_file import descriptor_to_type, method_parameter_types
from jar_parser.parser import compare_with_logs, join_paths, parse_jar

# .jar de PRUEBA (samples/demo_app): copia la API de la app del banco + un DELETE que no sale en los logs
DEMO_JAR = "samples/demo-bankapp.jar"


def find(endpoints, method, endpoint):
    for e in endpoints:
        if e["method"] == method and e["endpoint"] == endpoint:
            return e
    return None


def test_finds_all_endpoints_of_demo_jar():
    endpoints = parse_jar(DEMO_JAR)
    assert len(endpoints) == 12
    # @RequestMapping(method = RequestMethod.GET) también cuenta
    assert find(endpoints, "GET", "/api/users")["handler"] == "list"
    assert find(endpoints, "DELETE", "/api/accounts/{id}")["controller"] == "com.pae.bankapp.controller.AccountController"


def test_request_bodies_with_dto_fields():
    endpoints = parse_jar(DEMO_JAR)
    deposit = find(endpoints, "POST", "/api/accounts/{id}/deposit")
    assert deposit["body"] == {"type": "com.pae.bankapp.dto.DepositRequest", "fields": {"amount": "BigDecimal"}}
    transfer = find(endpoints, "POST", "/api/transfers")
    assert transfer["body"]["fields"] == {
        "fromAccountId": "Long", "toAccountId": "Long", "amount": "BigDecimal", "concept": "String",
    }
    assert find(endpoints, "GET", "/api/accounts/{id}")["body"] is None


def test_plain_jar_without_boot_inf(tmp_path):
    # Mismas clases pero en la raíz del .jar (un .jar normal, no de Spring Boot)
    plain = tmp_path / "plain.jar"
    with zipfile.ZipFile(DEMO_JAR) as source, zipfile.ZipFile(plain, "w") as target:
        for name in source.namelist():
            target.writestr(name.replace("BOOT-INF/classes/", ""), source.read(name))
    assert parse_jar(str(plain)) == parse_jar(DEMO_JAR)


def test_compare_with_logs():
    endpoints = parse_jar(DEMO_JAR)
    df = pd.DataFrame({"method": ["GET", "GET"], "endpoint": ["/api/users/{id}", "/api/old"]})
    coverage = compare_with_logs(endpoints, df)
    assert "DELETE /api/accounts/{id}" in coverage["never_used"]
    assert "GET /api/users/{id}" not in coverage["never_used"]
    assert coverage["unknown"] == ["GET /api/old"]


def test_join_paths():
    assert join_paths("/api/accounts", "/{id}/deposit") == "/api/accounts/{id}/deposit"
    assert join_paths("/api/accounts", "") == "/api/accounts"
    assert join_paths("api/users/", "{id}") == "/api/users/{id}"
    assert join_paths("", "") == "/"


def test_descriptors():
    assert descriptor_to_type("Ljava/math/BigDecimal;") == "java.math.BigDecimal"
    assert descriptor_to_type("J") == "long"
    assert descriptor_to_type("[I") == "int[]"
    assert method_parameter_types("(Ljava/lang/Long;I[Ljava/lang/String;)V") == ["java.lang.Long", "int", "java.lang.String[]"]
