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


def get_steps(df):
    """Tabla de peticiones con sesión, ordenada por tiempo, con dos columnas nuevas:

    - key:      nombre de la petición, p. ej. "GET /api/accounts/{id}"
    - next_key: la siguiente petición de la MISMA sesión (vacía en la última)
    """
    if "session_id" not in df.columns or df["session_id"].isna().all():
        raise ValueError(
            "Los logs no tienen el campo 'sessionId': sin él no se pueden reconstruir "
            "las secuencias de navegación (ver README)."
        )

    # Solo las peticiones con sesión, en orden de tiempo
    steps = df.dropna(subset=["session_id"])
    steps = steps.sort_values("timestamp", kind="stable").copy()

    # "GET" + " " + "/api/accounts/{id}"
    steps["key"] = steps["method"] + " " + steps["endpoint"]

    # groupby("session_id"): cada sesión por separado
    # shift(-1): el valor de la fila de abajo (la siguiente petición de esa sesión)
    steps["next_key"] = steps.groupby("session_id")["key"].shift(-1)
    return steps


def table_to_dict(table):
    """Tabla (filas = petición actual, columnas = siguiente) -> {actual: {siguiente: valor}},
    sin los ceros."""
    result = {}
    for source, row in table.iterrows():
        result[source] = {}
        for target, probability in row.items():
            if probability > 0:
                result[source][target] = float(probability)  # número normal de Python
    return result


def prune(probabilities, min_probability):
    """OPCIONAL: solo cambia algo si se ejecuta main.py con --min-probability (por defecto 0).

    Quita las opciones menos probables que min_probability y reparte su probabilidad
    entre las que quedan (para que sigan sumando 1). Si todas quedan por debajo, se
    queda la más probable. Sirve para simplificar el plan quitando caminos muy raros.
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

    - start_counts: {petición: nº de sesiones que empiezan por ella}
    - transition_counts: {actual: {siguiente: nº de veces}}, con END al final de cada sesión
    """
    steps = get_steps(df)

    # Cómo empiezan las sesiones: la primera petición de cada una, y cuántas veces
    first_requests = steps.groupby("session_id")["key"].first()
    start_counts = first_requests.value_counts().to_dict()

    # Después de la última petición de cada sesión viene END
    steps["next_key"] = steps["next_key"].fillna(END)

    # crosstab cuenta cuántas veces aparece cada pareja (actual, siguiente)
    table = pd.crosstab(steps["key"], steps["next_key"])
    transition_counts = table_to_dict(table)
    return start_counts, transition_counts


def mix(counts, options, jar_weight):
    """Mezcla lo visto en los logs con el .jar (el "prior") y lo pasa a probabilidades.

    El .jar no sabe cuánto se usa cada petición, así que reparte `jar_weight`
    "observaciones inventadas" a partes iguales entre todas las opciones:

        probabilidad = (veces en los logs + parte inventada) / (total en los logs + jar_weight)

    - Sin logs: solo cuentan las inventadas -> todas las opciones igual de probables.
    - Con muchos logs: las inventadas apenas se notan -> mandan los logs.
    - Sin .jar (options vacío): solo los logs, igual que antes.
    """
    invented = {}
    if options:
        for option in options:
            invented[option] = jar_weight / len(options)

    totals = {}
    for option in set(counts) | set(invented):
        totals[option] = counts.get(option, 0) + invented.get(option, 0)

    grand_total = sum(totals.values())
    if grand_total == 0:
        return {END: 1.0}  # no sabemos nada de esta petición (p. ej. jar_weight=0): se acaba la sesión
    probabilities = {}
    for option, total in totals.items():
        if total > 0:
            probabilities[option] = total / grand_total
    return probabilities


def build_markov_model(df=None, min_probability=0.0, max_steps=50, endpoints=None, jar_weight=1):
    """Modelo completo de navegación para simular sesiones, a partir de los logs (df),
    del .jar (endpoints) o de los dos:

    - states: todas las peticiones distintas (los estados de la cadena).
    - start: probabilidad de que una sesión empiece por cada petición.
    - transitions: probabilidad de la siguiente petición, incluido END (fin de sesión).
    - max_steps: límite de peticiones por sesión. No se usa aquí: se guarda en el modelo
      para que JMeter corte las sesiones que se alarguen demasiado (p. ej. por un bucle).

    jar_weight: cuántas "observaciones inventadas" aporta el .jar (ver mix()).
    """
    # 1. Lo que se ha visto en los logs (si hay)
    start_counts, transition_counts = {}, {}
    if df is not None and not df.empty:
        start_counts, transition_counts = count_from_logs(df)

    # 2. Lo que existe según el .jar (si hay)
    jar_requests = []
    if endpoints:
        for e in endpoints:
            jar_requests.append(e["method"] + " " + e["endpoint"])

    # 3. Todas las peticiones conocidas (de los logs y del .jar)
    states = set(start_counts) | set(transition_counts) | set(jar_requests)
    for targets in transition_counts.values():
        states |= set(targets) - {END}
    states = sorted(states)

    # 4. Mezclar: el .jar dice "cualquier petición puede empezar una sesión, y después
    #    de cualquiera puede venir cualquier otra o END, todas por igual"
    jar_start_options = jar_requests
    jar_next_options = jar_requests + [END] if jar_requests else []

    start = mix(start_counts, jar_start_options, jar_weight)
    transitions = {}
    for state in states:
        transitions[state] = mix(transition_counts.get(state, {}), jar_next_options, jar_weight)

    # OPCIONAL: con min_probability=0 (por defecto) prune no quita nada
    start = prune(start, min_probability)
    for source in transitions:
        transitions[source] = prune(transitions[source], min_probability)

    return {
        "states": states,
        "start": start,
        "transitions": transitions,
        "max_steps": max_steps,
    }
