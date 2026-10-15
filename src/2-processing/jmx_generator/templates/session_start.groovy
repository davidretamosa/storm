
// Nueva sesión: libreta de ids vacía, primera petición según model.start, sin pausa
vars.putObject("stormIds", [:])
goTo(pick(model.start))
vars.put("stormSteps", "0")
vars.put("stormThinkMs", "0")
