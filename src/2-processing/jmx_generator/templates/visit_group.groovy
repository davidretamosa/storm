
// Grupos de visita (--visit-groups): al empezar cada sesión elige un grupo según su peso y pone
// su modelo en stormModel. Los demás scripts lo leen de ahí (markov_common.groovy) y usan su
// start, transitions, status_transitions y think_time_ms. Variables del hilo:
//   stormGroups  pesos y modelos de los grupos (se preparan una vez por hilo)
//   stormGroup   número del grupo de la sesión actual
def groups = vars.getObject("stormGroups")
if (groups == null) {
    // Primera sesión del hilo: stormModel estaba vacío y `model` es el modelo general incrustado
    def data = new JsonSlurper().parseText(__GROUPS_JSON__)
    def models = data.groups.collect { part ->
        def groupModel = new LinkedHashMap(model)
        groupModel.putAll(part)
        groupModel
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
