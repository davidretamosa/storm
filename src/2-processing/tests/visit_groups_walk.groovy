// Banco de los grupos de visita (T-2.4): ejecuta los scripts JSR223 de un plan como lo hace JMeter, sin JMeter.
//   groovy visit_groups_walk.groovy <carpeta> <sesiones> <código>
// En la carpeta están pick.groovy (Elegir grupo de visita), start.groovy (Elegir primera petición) y
// next.groovy (Elegir siguiente petición), sacados del plan. Los compila con el motor javax.script de Groovy
// (el de JSR223: un literal demasiado largo falla igual que en JMeter) y hace N sesiones en un solo hilo que
// no borra nunca las variables (same_user_on_next_iteration): selector de grupo -> primera petición ->
// siguiente petición mientras la sesión siga. Todas las respuestas tienen el mismo código y el cuerpo
// {"id": 7}. Escribe una línea JSON por sesión en <carpeta>/walks.jsonl:
//   {"group": número del grupo, "steps": [[estado, pausa_ms, índice], ...], "skipped": true si se omitió una petición}
import groovy.json.JsonOutput
import javax.script.Compilable
import javax.script.ScriptEngineManager
import org.apache.jmeter.samplers.SampleResult
import org.apache.jmeter.threads.JMeterVariables

def dir = new File(args[0])
int sessions = args[1] as int
String code = args[2]

def engine = new ScriptEngineManager().getEngineByName("groovy")
def compiled = [:]
["pick", "start", "next"].each { name ->
    def text = new File(dir, name + ".groovy").getText("UTF-8")
    if (name == "next") {
        // Sin dormir: la pausa queda apuntada en stormPauseMs
        text = text.replace("Thread.sleep(pauseMs)", 'vars.put("stormPauseMs", String.valueOf(pauseMs))')
    }
    compiled[name] = ((Compilable) engine).compile(text)
}

def vars = new JMeterVariables()
def props = new Properties()
def prev = new SampleResult()
prev.setSuccessful(true)
prev.setResponseCode(code)
prev.setResponseData('{"id": 7}', "UTF-8")
def log = org.slf4j.LoggerFactory.getLogger("visit-groups-walk")

def run = { name ->
    def bindings = engine.createBindings()
    bindings.put("vars", vars)
    bindings.put("props", props)
    bindings.put("prev", prev)
    bindings.put("log", log)
    compiled[name].eval(bindings)
}

new File(dir, "walks.jsonl").withWriter("UTF-8") { out ->
    sessions.times {
        run("pick")
        run("start")
        def steps = []
        long pause = 0
        while (vars.get("stormState") != "END" && vars.get("stormSkipRequest") != "true") {
            steps << [vars.get("stormState"), pause, vars.get("stormIndex") as int]
            // next_request.groovy solo duerme si la pausa es > 0: sin esto, un paso sin pausa
            // heredaría la del paso anterior
            vars.put("stormPauseMs", "0")
            run("next")
            pause = vars.get("stormPauseMs") as long
        }
        out << JsonOutput.toJson([
            group: vars.get("stormGroup") as Integer,
            steps: steps,
            skipped: vars.get("stormSkipRequest") == "true",
        ]) << "\n"
    }
}
