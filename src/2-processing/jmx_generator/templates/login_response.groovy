
// Inicio de sesión: guarda el identificador que devuelve la app ({"sessionId": "abc123", ...});
// la cabecera de todas las peticiones de esta sesión lo usa (variable stormSessionId)
vars.put("stormSessionId", "")
if (prev.isSuccessful()) {
    try {
        def response = new JsonSlurper().parseText(prev.getResponseDataAsString())
        if (response instanceof Map && response[model.session.id_field] != null) {
            vars.put("stormSessionId", String.valueOf(response[model.session.id_field]))
        }
    } catch (Exception ignored) {
        // respuesta que no es JSON: sin sesión (las peticiones darán error, como en la app real)
    }
}
