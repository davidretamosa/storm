// STORM-IA (T-3, --ai-bodies): corregeix el body de la petició actual just abans d'enviar-la.
// Va com a JSR223 PreProcessor dins del While: corre abans de cada petició, quan el PostProcessor
// dels companys ja ha triat la petició (stormState) i el seu body (stormBody).
// Regles apreses dels logs i del .jar (ai/enhancements/bodies_learn.py i bodies_jar.py):
//   numbers    torna a sortejar cada número amb els quantils de les peticions que van anar bé
//   different  si dos camps coincideixen, torna a sortejar el que no ha posat la correlació
//   unique     posa un testimoni únic (execució-comptador) dins de la forma apresa
import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import java.math.RoundingMode
import java.util.concurrent.ThreadLocalRandom
import java.util.concurrent.atomic.AtomicLong

def rules = vars.getObject("stormAiBodies")
if (rules == null) {
    rules = new JsonSlurper().parseText('''__AI_BODIES_JSON__''')
    vars.putObject("stormAiBodies", rules)
}

def state = vars.get("stormState")
def text = vars.get("stormBody")
def rule = rules[state]
if (!rule || !text) {
    return
}

try {
    def body = new JsonSlurper().parseText(text)
    if (!(body instanceof Map)) {
        return
    }
    def random = ThreadLocalRandom.current()
    def model = vars.getObject("stormModel")

    // Camps que la correlació dels companys ja ha fixat (un id que l'app ens ha donat)
    def ids = vars.getObject("stormIds") ?: [:]
    def fixed = (model?.correlation?.body_resources?.get(state) ?: [:])
            .findAll { field, resource -> ids[resource] != null }
            .keySet()

    // 1. Números: CDF inversa amb els quantils (interpolació entre dos quantils seguits)
    rule.numbers.each { name, spec ->
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

    // 2. «Diferent»: es torna a sortejar el camp que no ha fixat la correlació, sense el valor repetit
    rule.different.each { pair ->
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

    // 3. «Únic»: prefix + testimoni + sufix; el comptador és de tot JMeter (tots els fils)
    rule.unique.each { name, form ->
        if (!body.containsKey(name)) {
            return
        }
        props.putIfAbsent("stormAiCounter", new AtomicLong())
        props.putIfAbsent("stormAiRun", Long.toString(System.currentTimeMillis(), 36))
        String token = props.get("stormAiRun") + "-" + props.get("stormAiCounter").incrementAndGet()
        String prefix = form.prefix
        String suffix = form.suffix
        if (form.max != null) {
            int room = (form.max as int) - token.length() - suffix.length()
            prefix = prefix.substring(0, Math.max(0, Math.min(prefix.length(), room)))
        }
        body[name] = prefix + token + suffix
    }

    vars.put("stormBody", JsonOutput.toJson(body))
} catch (Exception e) {
    log.error("STORM-IA bodies: " + state + ": " + e, e)
}
