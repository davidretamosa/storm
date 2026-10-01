// Modelo generado por STORM (2-processing). Variables del hilo:
//   stormState   petición actual ("GET /api/accounts/{id}") o "END"
//   stormIndex   posición de stormState en model.states (la usa el Switch Controller)
//   stormSteps   peticiones hechas en la sesión
//   stormThinkMs pausa antes de la siguiente petición
import groovy.json.JsonSlurper
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

def goTo = { String state ->
    vars.put("stormState", state)
    vars.put("stormIndex", String.valueOf(model.states.indexOf(state)))
}
