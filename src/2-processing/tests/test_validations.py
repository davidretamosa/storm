"""Valores que cumplen las reglas de validación del DTO (@Pattern, @Size, @Min, @Email, @JsonFormat...).

El .jar de prueba está compilado desde tests/fixtures/validation-app/src (anotaciones y Spring simulados).
"""
import re
from pathlib import Path

from jar_parser.parser import parse_jar
from traffic_model.payloads import build_body_models, format_java_date, schema_field_model
from traffic_model.regex_sample import sample

JAR = str(Path(__file__).parent / "fixtures" / "validation-app" / "validation-app.jar")


def models():
    return build_body_models(None, parse_jar(JAR))


def only(model):
    """El único valor posible de un campo 'choice'."""
    assert len(model["values"]) == 1
    return model["values"][0][0]


def test_regex_sample_matches_the_pattern():
    for pattern in [r"^[0-9]*$", r"\d{10}", r"[A-Z]{2}\d{22}", r"^(\+34)?[6-9][0-9]{8}$", r"[a-z]+@[a-z]+\.com", r"^[^@]+$"]:
        assert re.fullmatch(pattern, sample(pattern)), pattern


def test_regex_sample_tries_to_fit_the_length():
    value = sample(r"^[0-9]*$", 10, 20)
    assert 10 <= len(value) <= 20


def test_regex_sample_gives_up_on_java_only_syntax():
    assert sample(r"\p{Alpha}+") is None


def test_java_date_patterns():
    assert format_java_date("dd/MM/yyyy", 2030, 6, 15) == "15/06/2030"
    assert format_java_date("yyyy-MM-dd'T'HH:mm:ss", 2026, 1, 2) == "2026-01-02T14:30:45"
    assert format_java_date("d MMM yy", 2026, 3, 5) == "5 Mar 26"


def test_parser_reads_validation_rules_from_fields_and_getters():
    endpoints = {e["endpoint"]: e for e in parse_jar(JAR)}
    owner = endpoints["/api/owners"]["body"]["schema"]
    assert owner["firstName"]["rules"] == {"min_len": 1, "max_len": 30}              # anotación en el campo
    assert owner["telephone"]["rules"]["pattern"] == "^[0-9]*$"                       # anotación en el getter
    assert owner["telephone"]["rules"]["max_len"] == 20
    assert "id" in owner                                                              # campo heredado
    booking = endpoints["/api/bookings"]["body"]["schema"]
    assert booking["roomNumber"]["rules"] == {"min": 1, "max": 9}
    assert booking["checkIn"]["rules"] == {"future": True, "format": "dd/MM/yyyy"}
    assert booking["status"]["enum"] == ["ACTIVE", "CLOSED"]


def test_owner_phone_matches_its_pattern():
    owner = models()["POST /api/owners"]
    assert re.fullmatch(r"^[0-9]*$", only(owner["telephone"]))
    assert re.fullmatch(r"\d{10}", only(owner["telephone"]))      # la regla de la entidad Owner también
    assert 1 <= len(only(owner["firstName"])) <= 30


def test_rules_of_the_entity_with_the_same_name_are_added():
    """El DTO (OwnerDto) solo pide dígitos; la entidad (Owner) pide exactamente 10 y @Digits(integer=5)."""
    owner = {e["endpoint"]: e for e in parse_jar(JAR)}["/api/owners"]["body"]["schema"]
    assert owner["telephone"]["rules"]["pattern"] == "^[0-9]*$"
    assert owner["telephone"]["rules"]["patterns"] == ["\\d{10}"]
    assert re.fullmatch(r"\d{5}", only(models()["POST /api/owners"]["zip"]))


def test_numbers_and_dates_follow_the_rules():
    booking = models()["POST /api/bookings"]
    assert (booking["roomNumber"]["min"], booking["roomNumber"]["max"]) == (1, 9)
    dates = [value for value, _ in booking["checkIn"]["values"]]
    assert dates[0] == "15/06/2030"                           # dd/MM/yyyy y en el futuro
    assert len(set(dates)) == 365                             # una fecha distinta por día: sin 409 por reservas repetidas
    assert dates[1] == "16/06/2030" and dates[-1] == "14/06/2031"
    assert all(re.fullmatch(r"\d\d/\d\d/(2030|2031)", value) for value in dates)
    assert re.fullmatch(r"[^@]+@[^@]+\.[a-z]+", only(booking["guestEmail"]))
    assert [value for value, _ in booking["status"]["values"]] == ["ACTIVE", "CLOSED"]


def test_lists_are_empty_unless_the_dto_asks_for_elements():
    vet = models()["POST /api/vets"]
    assert only(vet["specialties"]) == []                    # @NotNull: vale una lista vacía
    booking = models()["POST /api/bookings"]
    assert only(booking["extras"]) == [{"id": 1, "name": "test"}]   # @NotEmpty: un elemento
    assert only(booking["main"]) == {"id": 1, "name": "test"}       # objeto anidado


def test_unknown_types_are_still_skipped():
    assert schema_field_model("thing", {"type": "Object", "rules": {}}) is None


def test_entity_of_dto_names():
    from jar_parser.parser import entity_of
    classes = {name: {} for name in ["a.Owner", "a.OwnerDto", "a.OwnerFieldsDto", "a.PetType", "a.PetTypeDto", "a.Thing"]}
    assert entity_of(classes, "a.OwnerDto") == "a.Owner"
    assert entity_of(classes, "a.OwnerFieldsDto") == "a.Owner"      # OwnerFields -> Owner
    assert entity_of(classes, "a.PetTypeDto") == "a.PetType"
    assert entity_of(classes, "a.Thing") is None                    # no es un DTO
    assert entity_of({"a.OwnerDto": {}}, "a.OwnerDto") is None      # sin entidad


def test_past_dates_go_backwards():
    model = schema_field_model("birthDate", {"type": "LocalDate", "rules": {}})
    dates = [value for value, _ in model["values"]]
    assert dates[0] == "2020-06-15" and dates[1] == "2020-06-14"
