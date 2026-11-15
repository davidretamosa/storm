// Tras cada petición: elige la siguiente según model.transitions y la pausa hasta ella
def current = vars.get("stormState")

rememberCreatedId(current, prev)
rememberDeletedId(current, prev)

int steps = Integer.parseInt(vars.get("stormSteps")) + 1
vars.put("stormSteps", String.valueOf(steps))

def next = pick(model.transitions[current] ?: [END: 1])

if (steps >= model.max_steps) {
    next = "END"
}

if (next == "END") {
    vars.put("stormState", "END")
    return
}

// Calcular y aplicar la pausa antes de preparar la petición
def pauses = model.think_time_ms[current]?.get(next)

long pauseMs = pauses ?
    (pauses[ThreadLocalRandom.current().nextInt(pauses.size())] as long) : 0L

if (pauseMs > 0) {
    try {
        Thread.sleep(pauseMs)
    } catch (InterruptedException e) {
        Thread.currentThread().interrupt()
        vars.put("stormState", "END")
        return
    }
}

// Seleccionar los identificadores después de la pausa
goTo(next)