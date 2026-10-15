
// Nueva sesión: libreta de ids vacía, primera petición según model.start, sin pausa
vars.putObject("stormIds", [:])

// Si la app pide iniciar sesión: con qué usuario (el POST lo hace el plan justo después)
if (model.session) {
    def login = [:]
    login[model.session.user_field] = pickValue(model.session.users)
    vars.put("stormLoginBody", JsonOutput.toJson(login))
}

goTo(pick(model.start))
vars.put("stormSteps", "0")
vars.put("stormThinkMs", "0")
