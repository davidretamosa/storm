// Modelo generado por STORM (2-processing). Variables del hilo:
//   stormState   petición actual ("GET /api/accounts/{id}") o "END"
//   stormIndex   posición de stormState en model.states
//   stormSteps   peticiones hechas en la sesión
//   stormThinkMs pausa antes de la siguiente petición
//   stormBody    cuerpo JSON de la petición actual
//   <param>      valor de cada parámetro de la ruta
//   stormIds     ids que la app ha devuelto en esta sesión

import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import java.math.RoundingMode
import java.util.concurrent.ThreadLocalRandom

def model = vars.getObject("stormModel")
if (model == null) {
    model = new JsonSlurper().parseText('''__MODEL_JSON__''')
    vars.putObject("stormModel", model)
}

// Elige una clave según su probabilidad
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

// Cuerpo JSON a partir del modelo de cada campo
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

// Correlación entre peticiones y recursos
def correlation = model.correlation ?: [:]

// Registro compartido de recursos eliminados durante la prueba
def deletedIds = props.get("stormDeletedIds")

if (deletedIds == null) {
    synchronized (props) {
        deletedIds = props.get("stormDeletedIds")

        if (deletedIds == null) {
            deletedIds = new java.util.concurrent.ConcurrentHashMap()
            props.put("stormDeletedIds", deletedIds)
        }
    }
}
// Registro compartido de recursos disponibles durante la prueba
def availableIds = props.get("stormAvailableIds")

if (availableIds == null) {
    synchronized (props) {
        availableIds = props.get("stormAvailableIds")

        if (availableIds == null) {
            availableIds = new java.util.concurrent.ConcurrentHashMap()
            props.put("stormAvailableIds", availableIds)
        }
    }
}

// Prepara la petición: índice, parámetros de ruta y cuerpo
def goTo = { String state ->
    vars.put("stormSkipRequest", "false")
    vars.put("stormState", state)
    vars.put("stormIndex", String.valueOf(model.states.indexOf(state)))
    def ids = vars.getObject("stormIds") ?: [:]

    // Selección de identificadores de recursos no eliminados
    def params = new LinkedHashMap(model.path_params[state] ?: [:])
    def links = correlation.path_resources?.get(state) ?: [:]

    // Inicializar todos los parámetros de la ruta,
    // incluso si la petición no aparece en los logs
    def matcher = state =~ /\{(\w+)\}/

    while (matcher.find()) {
        def name = matcher.group(1)

        if (!params.containsKey(name)) {
            params[name] = []
        }
    }

    for (param in params) {
        def resource = links[param.key]
        def removed = resource ? (deletedIds[resource] ?: []) : []

        // Identificadores aprendidos que no han sido eliminados
        def candidates = (param.value ?: []).findAll {
            !removed.contains(String.valueOf(it[0]))
        }

        // Identificadores disponibles creados durante la prueba
        def available = resource ? (availableIds[resource] ?: []) : []

        def dynamicCandidates = available.findAll {
            !removed.contains(String.valueOf(it))
        }.toList()

        def createdId = resource ? ids[resource] : null
        def value = null

        // 1. Priorizar el identificador de la sesión
        if (createdId != null &&
            !removed.contains(String.valueOf(createdId))) {

            value = createdId

        // 2. Utilizar identificadores aprendidos
        } else if (candidates) {

            def total = candidates.sum { it[1] }

            def normalized = candidates.collect {
                [it[0], it[1] / total]
            }

            value = pickValue(normalized)

        // 3. Utilizar recursos disponibles creados durante la prueba
        } else if (dynamicCandidates) {

            def index = ThreadLocalRandom.current()
                .nextInt(dynamicCandidates.size())

            value = dynamicCandidates[index]
        }

        // 4. No hay identificadores disponibles
        if (value == null) {
            log.warn("STORM: Petición omitida sin identificador: " + state)

            vars.put("stormSkipRequest", "true")
            vars.put("stormState", "END")
            return
        } else {
            vars.put(param.key, String.valueOf(value))
        }
    }
    // Seleccionar los parámetros de consulta según su distribución
    def queries = model.query_params?.get(state) ?: []
    def query = queries ? pickValue(queries) : ""

    vars.put("stormQuery", query ? "?" + query : "")
    // Seleccionar las cabeceras HTTP según su distribución
    def headerDistribution = model.header_models?.get(state) ?: []

    def selectedHeaders = headerDistribution ?
        pickValue(headerDistribution) : [:]

    vars.putObject("stormHeaders", selectedHeaders ?: [:])
    def bodyModel = model.bodies[state]
    if (bodyModel) {
        def body = buildBody(bodyModel)

        // Reutilizar identificadores en el cuerpo JSON
        for (link in (correlation.body_resources?.get(state) ?: [:])) {
    def id = ids[link.value]
    def removed = deletedIds[link.value] ?: []

    // Reutilizar el identificador solo si no ha sido eliminado
    if (body.containsKey(link.key) &&
        id != null &&
        !removed.contains(String.valueOf(id))) {

        body[link.key] = id
    }
}

        vars.put("stormBody", JsonOutput.toJson(body))
    } else {
        vars.put("stormBody", "")
    }
}

// Registra el identificador de un recurso creado
def rememberCreatedId = { String state, def result ->
    def resource = correlation.creates?.get(state)

    if (!resource || !result.isSuccessful()) {
        return
    }

    try {
        def response = new JsonSlurper().parseText(
            result.getResponseDataAsString()
        )

        if (response instanceof Map && response.id != null) {
            def ids = vars.getObject("stormIds") ?: [:]
            ids[resource] = response.id
            vars.putObject("stormIds", ids)

            // Registrar el recurso como disponible
            def id = String.valueOf(response.id)

            deletedIds[resource]?.remove(id)

            availableIds.computeIfAbsent(resource) {
                java.util.concurrent.ConcurrentHashMap.newKeySet()
            }.add(id)
        }
    } catch (Exception ignored) {
        // Respuesta vacía o que no es JSON
    }
}

// Registra el identificador de un recurso eliminado correctamente
def rememberDeletedId = { String state, def result ->
    def deletion = correlation.deletes?.get(state)

    if (!deletion || !result.isSuccessful()) {
        return
    }

    if (!(result.getResponseCode() in ["200", "204"])) {
        return
    }

    def resource = deletion.resource
    def id = vars.get(deletion.param)

    if (id != null) {
        // Retirar el recurso del registro de disponibles
        availableIds[resource]?.remove(id)

        // Registrar el recurso como eliminado
        deletedIds.computeIfAbsent(resource) {
            java.util.concurrent.ConcurrentHashMap.newKeySet()
        }.add(id)
    }
}