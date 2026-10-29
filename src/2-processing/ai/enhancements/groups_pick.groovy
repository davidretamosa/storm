// STORM-IA (T-2), grups de visita: a l'inici de cada sessió tria un grup segons el seu pes i en posa el model
// a stormModel. Els scripts de STORM el fan servir sense saber-ho: markov_common.groovy només llegeix el model
// incrustat si stormModel és buit. Variables del fil que afegeix:
//   stormGroups (objecte) pesos i models dels grups, preparats un cop per fil
//   stormGroup  índex del grup de la sessió actual
import groovy.json.JsonSlurper
import java.util.concurrent.ThreadLocalRandom

def groups = vars.getObject("stormGroups")
if (groups == null) {
    def base = new JsonSlurper().parseText('''__BASE_MODEL_JSON__''')
    def data = new JsonSlurper().parseText('''__GROUPS_JSON__''')
    // Cada grup: el model de STORM amb el seu propi inici, transicions i pauses
    def models = data.groups.collect { group ->
        def model = new LinkedHashMap(base)
        model.putAll(group)
        model
    }
    groups = [weights: data.weights, models: models]
    vars.putObject("stormGroups", groups)
}

double r = ThreadLocalRandom.current().nextDouble()
double acc = 0
int chosen = groups.weights.size() - 1
for (int i = 0; i < groups.weights.size(); i++) {
    acc += groups.weights[i] as double
    if (r < acc) {
        chosen = i
        break
    }
}
vars.put("stormGroup", String.valueOf(chosen))
vars.putObject("stormModel", groups.models[chosen])
