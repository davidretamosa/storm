
"""Cadena de Markov de la navegación: qué petición sigue a cuál dentro de una sesión.

Ejemplo: si en los logs, después de "GET /api/accounts/{id}", 6 veces viene una
transferencia y 4 veces se consultan los movimientos, la probabilidad de cada una
es 0.6 y 0.4. JMeter usará esas probabilidades para decidir qué hace cada usuario.

La función que usa main.py es build_markov_model(). Combina lo que se ve en los logs
con lo que existe en el .jar (ver mix()). Las demás son piezas suyas
(get_steps también la usa think_time.py).
"""

import pandas as pd

# Estado final: la sesión termina después de la petición actual
END = "END"
# Probabilidad estimada de finalizar una sesión sin sessionId
DEFAULT_END_PROBABILITY = 0.1


def get_steps(df):
    """Tabla de peticiones con sesión, ordenada por tiempo, con dos columnas nuevas:

    - key: nombre de la petición, p. ej. "GET /api/accounts/{id}"
    - next_key: la siguiente petición de la MISMA sesión (vacía en la última).
    """

    if "session_id" not in df.columns or df["session_id"].isna().all():
        raise ValueError(
            "Los logs no tienen el campo 'sessionId': sin él no se pueden reconstruir "
            "las secuencias de navegación (ver README)."
        )

    # Solo las peticiones con sesión, en orden de tiempo
    steps = df.dropna(subset=["session_id"])
    steps = steps.sort_values("timestamp", kind="stable").copy()

    # Identificador de cada petición HTTP
    steps["key"] = steps["method"] + " " + steps["endpoint"]

    # Obtener la siguiente petición de cada sesión
    steps["next_key"] = steps.groupby("session_id")["key"].shift(-1)

    return steps


def table_to_dict(table):
    """Tabla de transiciones -> {actual: {siguiente: valor}}, sin los ceros."""

    result = {}

    for source, row in table.iterrows():
        result[source] = {}

        for target, probability in row.items():
            if probability > 0:
                result[source][target] = float(probability)

    return result


def prune(probabilities, min_probability):
    """Elimina las opciones inferiores al umbral y normaliza las restantes.

    Si todas quedan por debajo, se conserva la más probable.
    """

    kept = {}

    for key, probability in probabilities.items():
        if probability >= min_probability:
            kept[key] = probability

    if not kept:
        best = max(probabilities, key=probabilities.get)
        kept[best] = probabilities[best]

    total = sum(kept.values())

    result = {}

    for key, probability in kept.items():
        result[key] = probability / total

    return result


def count_from_logs(df):
    """Cuántas veces pasa cada cosa en los logs:

    - start_counts: número de sesiones que empiezan por cada petición.
    - transition_counts: número de transiciones entre peticiones,
      incluyendo END al final de cada sesión.
    """

    # Si los logs no tienen identificadores de sesión,
    # no podemos reconstruir las transiciones reales.
    if "session_id" not in df.columns or df["session_id"].isna().all():

        frequencies = (
            df["method"] + " " + df["endpoint"]
        ).value_counts().to_dict()

        # Utilizar las frecuencias globales como distribución inicial
        start_counts = frequencies.copy()

        # Mantener una probabilidad de END independiente
        # del número de peticiones de los logs.
        total = sum(frequencies.values())

        end_weight = (
            total * DEFAULT_END_PROBABILITY
            / (1 - DEFAULT_END_PROBABILITY)
        )

        transition_counts = {
            endpoint: {**frequencies, END: end_weight}
            for endpoint in frequencies
        }

        return start_counts, transition_counts

    # Peticiones con identificador de sesión
    steps = get_steps(df)

    # Primera petición de cada sesión
    first_requests = steps.groupby("session_id")["key"].first()
    start_counts = first_requests.value_counts().to_dict()

    # Después de la última petición de cada sesión viene END
    steps["next_key"] = steps["next_key"].fillna(END)

    # Contar las transiciones observadas
    table = pd.crosstab(steps["key"], steps["next_key"])
    transition_counts = table_to_dict(table)

    # Incorporar las peticiones sin identificador de sesión
    without_session = df[df["session_id"].isna()]

    frequencies = (
        without_session["method"] + " " +
        without_session["endpoint"]
    ).value_counts().to_dict()

    for state, count in frequencies.items():

        # Cada petición sin sesión se considera independiente
        start_counts[state] = start_counts.get(state, 0) + count

        targets = transition_counts.setdefault(state, {})
        targets[END] = targets.get(END, 0) + count

    return start_counts, transition_counts


def build_status_transitions(df):
    """Aprende transiciones condicionadas al código de respuesta HTTP."""

    # Sin sesiones o códigos HTTP no se pueden aprender
    # transiciones condicionadas.
    if df is None or df.empty:
        return {}

    if "session_id" not in df.columns or "status" not in df.columns:
        return {}

    if df["session_id"].isna().all():
        return {}

    steps = get_steps(df)

    steps["next_key"] = steps["next_key"].fillna(END)
    steps = steps.dropna(subset=["status"])

    result = {}

    for (state, status), group in steps.groupby(["key", "status"]):

        probabilities = (
            group["next_key"]
            .value_counts(normalize=True)
            .to_dict()
        )

        result.setdefault(state, {})[str(int(status))] = {
            target: float(probability)
            for target, probability in probabilities.items()
        }

    return result


def mix(counts, options, jar_weight):
    """Mezcla lo observado en los logs con el prior del JAR.

    El JAR reparte jar_weight observaciones estimadas
    a partes iguales entre todas las opciones.

    - Sin logs: todas las opciones tienen la misma probabilidad.
    - Con muchos logs: predominan las observaciones reales.
    - Sin JAR: solo se utilizan los logs.
    """

    invented = {}

    if options:
        for option in options:
            invented[option] = jar_weight / len(options)

    totals = {}

    for option in set(counts) | set(invented):
        totals[option] = (
            counts.get(option, 0) +
            invented.get(option, 0)
        )

    grand_total = sum(totals.values())

    if grand_total == 0:
        return {END: 1.0}

    probabilities = {}

    for option, total in totals.items():
        if total > 0:
            probabilities[option] = total / grand_total

    return probabilities


def build_markov_model(
    df=None,
    min_probability=0.0,
    max_steps=50,
    endpoints=None,
    jar_weight=1
):
    """Construye el modelo completo de navegación a partir de logs y/o JAR.

    - states: todas las peticiones conocidas.
    - start: probabilidades iniciales de las sesiones.
    - transitions: probabilidades de transición entre peticiones.
    - status_transitions: transiciones condicionadas al código HTTP.
    - max_steps: límite de peticiones por sesión.

    jar_weight determina el peso de la información extraída del JAR.
    """

    # 1. Información observada en los logs
    start_counts, transition_counts = {}, {}

    if df is not None and not df.empty:
        start_counts, transition_counts = count_from_logs(df)

    # 2. Peticiones extraídas del JAR
    jar_requests = []

    if endpoints:
        for e in endpoints:
            jar_requests.append(
                e["method"] + " " + e["endpoint"]
            )

    # 3. Todas las peticiones conocidas
    states = (
        set(start_counts)
        | set(transition_counts)
        | set(jar_requests)
    )

    for targets in transition_counts.values():
        states |= set(targets) - {END}

    states = sorted(states)

    # 4. Combinar la información de los logs y del JAR
    jar_start_options = jar_requests

    jar_next_options = (
        jar_requests + [END] if jar_requests else []
    )

    start = mix(
        start_counts,
        jar_start_options,
        jar_weight
    )

    transitions = {}

    for state in states:
        transitions[state] = mix(
            transition_counts.get(state, {}),
            jar_next_options,
            jar_weight
        )

    # 5. Filtrar las probabilidades generales
    start = prune(start, min_probability)

    for source in transitions:
        transitions[source] = prune(
            transitions[source],
            min_probability
        )

    # 6. Construir y filtrar las transiciones condicionadas
    status_transitions = build_status_transitions(df)

    for state, statuses in status_transitions.items():
        for status, probabilities in statuses.items():
            statuses[status] = prune(
                probabilities,
                min_probability
            )

    return {
        "states": states,
        "start": start,
        "transitions": transitions,
        "status_transitions": status_transitions,
        "max_steps": max_steps,
    }
