// Modelo generado por STORM (2-processing). Variables del hilo:
//   stormState   petición actual ("GET /api/accounts/{id}") o "END"
//   stormIndex   posición de stormState en model.states (la usa el Switch Controller)
//   stormSteps   peticiones hechas en la sesión
//   stormThinkMs pausa antes de la siguiente petición
//   stormBody    cuerpo JSON de la petición actual ("" si no lleva)
//   <param>      valor de cada {param} de la ruta de la petición actual
//   stormIds     (objeto) ids que la app ha devuelto en esta sesión: {"/api/accounts": 47, ...}
import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import java.math.RoundingMode
import java.util.concurrent.ThreadLocalRandom

def model = vars.getObject("stormModel")
if (model == null) {
    model = new JsonSlurper().parseText('''__MODEL_JSON__''')
    vars.putObject("stormModel", model)
}

// Elige una clave de {clave: probabilidad} según su probabilidad
def pick = { Map distribution ->
    double r = ThreadLocalRandom.current().nextDouble()
    double acc = 0
    def chosen = null
    for (entry in distribution) {
        chosen = entry.key
        acc += entry.value
        if (r < acc) {
            break
        }
    }
    return chosen
}

// Elige un valor de [[valor, probabilidad], ...]
def pickValue = { List weighted ->
    double r = ThreadLocalRandom.current().nextDouble()
    double acc = 0
    def chosen = null
    for (pair in weighted) {
        chosen = pair[0]
        acc += pair[1]
        if (r < acc) {
            break
        }
    }
    return chosen
}

// Cuerpo JSON a partir del modelo de cada campo (ver traffic_model/payloads.py)
def buildBody = { Map fields ->
    def body = [:]
    for (field in fields) {
        def spec = field.value
        if (ThreadLocalRandom.current().nextDouble() >= (spec.presence as double)) {
            continue
        }
        if (spec.type == "number") {
            double min = spec.min as double
            double max = spec.max as double
            double x = min + ThreadLocalRandom.current().nextDouble() * (max - min)
            int decimals = spec.decimals as int
            body[field.key] = decimals == 0 ? Math.round(x) : new BigDecimal(x).setScale(decimals, RoundingMode.HALF_UP)
        } else {
            body[field.key] = pickValue(spec.values)
        }
    }
    return body
}

// Correlación: qué crea cada petición y qué ids pueden reutilizar lo creado (traffic_model/correlation.py)
def correlation = model.correlation ?: [:]

// Prepara la petición: índice para el Switch, parámetros de ruta y cuerpo
def goTo = { String state ->
    vars.put("stormState", state)
    vars.put("stormIndex", String.valueOf(model.states.indexOf(state)))
    def ids = vars.getObject("stormIds") ?: [:]

    // {id} de la ruta: uno de los vistos en los logs (o 1)...
    def params = model.path_params[state] ?: [:]
    for (param in params) {
        def value = param.value ? pickValue(param.value) : 1
        vars.put(param.key, String.valueOf(value))
    }
    // ...salvo que en esta sesión la app nos haya dado uno de ese recurso: entonces, ese
    for (link in (correlation.path_resources?.get(state) ?: [:])) {
        if (ids[link.value] != null) {
            vars.put(link.key, String.valueOf(ids[link.value]))
        }
    }

    def bodyModel = model.bodies[state]
    if (bodyModel) {
        def body = buildBody(bodyModel)
        // Lo mismo con los ids del body (p. ej. userId, fromAccountId)
        for (link in (correlation.body_resources?.get(state) ?: [:])) {
            if (body.containsKey(link.key) && ids[link.value] != null) {
                body[link.key] = ids[link.value]
            }
        }
        vars.put("stormBody", JsonOutput.toJson(body))
    } else {
        vars.put("stormBody", "")
    }
}

// Si la petición que acaba de hacerse creaba algo, apunta el id que ha devuelto la app
def rememberCreatedId = { String state, def result ->
    def resource = correlation.creates?.get(state)
    if (!resource || !result.isSuccessful()) {
        return
    }
    try {
        def response = new JsonSlurper().parseText(result.getResponseDataAsString())
        if (response instanceof Map && response.id != null) {
            def ids = vars.getObject("stormIds") ?: [:]
            ids[resource] = response.id
            vars.putObject("stormIds", ids)
        }
    } catch (Exception ignored) {
        // respuesta vacía o que no es JSON: no hay id que apuntar
    }
}
