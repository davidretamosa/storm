// Modelo generado por STORM (2-processing). Variables del hilo:
//   stormState   petición actual ("GET /api/accounts/{id}") o "END"
//   stormIndex   posición de stormState en model.states (la usa el Switch Controller)
//   stormSteps   peticiones hechas en la sesión
//   stormThinkMs pausa antes de la siguiente petición
//   stormBody    cuerpo JSON de la petición actual ("" si no lleva)
//   <param>      valor de cada {param} de la ruta de la petición actual
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

// Prepara la petición: índice para el Switch, parámetros de ruta y cuerpo
def goTo = { String state ->
    vars.put("stormState", state)
    vars.put("stormIndex", String.valueOf(model.states.indexOf(state)))
    def params = model.path_params[state] ?: [:]
    for (param in params) {
        def value = param.value ? pickValue(param.value) : 1
        vars.put(param.key, String.valueOf(value))
    }
    def bodyModel = model.bodies[state]
    vars.put("stormBody", bodyModel ? JsonOutput.toJson(buildBody(bodyModel)) : "")
}
