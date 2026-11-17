// STORM-IA (capa de IA, flag --realistic-bodies): corrige el body de la petición actual justo antes de enviarla.
// Va como JSR223 PreProcessor, primer hijo del While: corre antes de cada petición, cuando el PostProcessor
// «Elegir siguiente petición (Markov)» (o «Elegir primera petición») ya ha dejado stormState y stormBody.
// Reglas aprendidas del log y del .jar (traffic_model/body_rules.py), por petición:
//   numbers    vuelve a sortear cada número con los cuantiles de las peticiones que fueron bien (2xx)
//   different  si dos campos coinciden, vuelve a sortear el que no ha fijado la correlación
//   unique     pone un testigo único (ejecución-contador) dentro de la forma aprendida
// Si algo falla, stormBody queda intacto (solo se escribe al final) y sale una línea de error en el jmeter.log.
import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import java.math.RoundingMode
import java.util.concurrent.ThreadLocalRandom
import java.util.concurrent.atomic.AtomicLong

def state = null
try {
    // Las reglas se leen una vez por hilo
    def rules = vars.getObject("stormBodyRules")
    if (rules == null) {
        rules = new JsonSlurper().parseText('''__BODY_RULES_JSON__''')
        vars.putObject("stormBodyRules", rules)
    }

    state = vars.get("stormState")
    def text = vars.get("stormBody")
    def rule = rules[state]
    if (!rule || !text) {
        return
    }

    // Un body que no es un objeto JSON no se toca (y no es un error)
    def body
    try {
        body = new JsonSlurper().parseText(text)
    } catch (Exception ignored) {
        return
    }
    if (!(body instanceof Map)) {
        return
    }

    def random = ThreadLocalRandom.current()
    def model = vars.getObject("stormModel")

    // Campos que ha fijado la correlación: la misma condición con la que markov_common.groovy los pone
    // (el campo está en el body, la sesión tiene un id de ese recurso y ese id no está entre los eliminados)
    def ids = vars.getObject("stormIds")
    def deleted = props.get("stormDeletedIds")
    def fixed = [] as Set
    def links = model?.correlation?.body_resources?.get(state)
    if (links && ids != null) {
        links.each { field, resource ->
            def id = ids[resource]
            def removed = deleted?.get(resource) ?: []
            if (body.containsKey(field) && id != null && !removed.contains(String.valueOf(id))) {
                fixed << field
            }
        }
    }

    // 1. Números: CDF inversa con los cuantiles (interpolación lineal entre dos cuantiles seguidos)
    (rule.numbers ?: [:]).each { name, spec ->
        if (!body.containsKey(name) || fixed.contains(name)) {
            return
        }
        List q = spec.q
        double u = random.nextDouble() * (q.size() - 1)
        int i = (int) Math.floor(u)
        double low = q[i] as double
        double high = q[Math.min(i + 1, q.size() - 1)] as double
        double x = low + (u - i) * (high - low)
        int decimals = spec.decimals as int
        body[name] = decimals == 0 ? Math.round(x) : new BigDecimal(x).setScale(decimals, RoundingMode.HALF_UP)
    }

    // 2. «Distinto»: si coinciden, se vuelve a sortear el campo que no ha fijado la correlación,
    //    entre los valores del modelo que no son el del otro campo (con sus pesos normalizados)
    (rule.different ?: []).each { pair ->
        def a = pair[0]
        def b = pair[1]
        if (!body.containsKey(a) || !body.containsKey(b) || String.valueOf(body[a]) != String.valueOf(body[b])) {
            return
        }
        if (fixed.contains(a) && fixed.contains(b)) {
            return
        }
        def target = fixed.contains(b) ? a : b
        def other = String.valueOf(body[target == a ? b : a])
        def options = (model?.bodies?.get(state)?.get(target)?.values ?: []).findAll { String.valueOf(it[0]) != other }
        if (!options) {
            return
        }
        double total = options.sum { it[1] as double }
        double r = random.nextDouble() * total
        double acc = 0
        def chosen = options[-1][0]
        for (option in options) {
            acc += option[1] as double
            if (r < acc) {
                chosen = option[0]
                break
            }
        }
        body[target] = chosen
    }

    // 3. «Único»: prefijo + testigo + sufijo. El contador es de toda la JVM (todos los hilos) y el testigo
    //    lleva la hora de arranque en base 36, así que tampoco se repite entre ejecuciones (salvo en el modo
    //    «solo contador», donde no cabe la hora: ahí cada ejecución vuelve a empezar por 1).
    //    Con longitud máxima: si testigo + sufijo no caben, el valor es solo el contador en base 36 + sufijo,
    //    sin prefijo (un prefijo recortado según la longitud del contador haría repetir valores: "sto" + "1"
    //    y "st" + "o1"); si caben, el prefijo se acorta hasta donde quepa. Con longitud mínima: se rellena
    //    con "x" después del prefijo; en el modo «solo contador» el relleno acaba en "-", porque la "x" también
    //    es una cifra de la base 36 ("xxx" + "1" y "xx" + "x1" darían lo mismo).
    (rule.unique ?: [:]).each { name, form ->
        if (!body.containsKey(name) || fixed.contains(name)) {
            return
        }
        props.putIfAbsent("stormBodyCounter", new AtomicLong())
        props.putIfAbsent("stormBodyRun", Long.toString(System.currentTimeMillis(), 36))
        long count = props.get("stormBodyCounter").incrementAndGet()
        String token = props.get("stormBodyRun") + "-" + count
        String prefix = form.prefix ?: ""
        String suffix = form.suffix ?: ""
        boolean onlyCounter = false
        if (form.max != null) {
            int max = form.max as int
            if (token.length() + suffix.length() > max) {
                token = Long.toString(count, 36)
                prefix = ""
                onlyCounter = true
            }
            int room = max - token.length() - suffix.length()
            prefix = prefix.substring(0, Math.max(0, Math.min(prefix.length(), room)))
        }
        if (form.min != null) {
            int missing = (form.min as int) - (prefix + token + suffix).length()
            if (missing > 0) {
                prefix = prefix + (onlyCounter ? "x" * (missing - 1) + "-" : "x" * missing)
            }
        }
        String value = prefix + token + suffix
        if (form.max != null && value.length() > (form.max as int)) {
            // Ni el contador solo y el sufijo caben: se corta por el final (el testigo, al principio, se queda)
            value = value.substring(0, form.max as int)
        }
        body[name] = value
    }

    vars.put("stormBody", JsonOutput.toJson(body))
} catch (Exception e) {
    log.error("STORM-IA bodies: " + state + ": " + e, e)
}
