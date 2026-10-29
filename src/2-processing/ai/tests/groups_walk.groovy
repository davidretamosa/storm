// Prova del T-2: fa córrer els scripts JSR223 d'un pla com ho fa JMeter, sense JMeter.
//   groovy groups_walk.groovy <carpeta amb pick.groovy, start.groovy i next.groovy> <sessions>
// Els compila amb el motor javax.script de Groovy (el de JSR223: un literal massa llarg hi falla igual que a
// JMeter) i fa N sessions en un sol fil que no esborra mai les variables (same_user_on_next_iteration):
// selector de grup (si n'hi ha) -> primera petició -> següent petició fins a END. Una línia JSON per sessió.
import groovy.json.JsonOutput
import javax.script.Compilable
import javax.script.ScriptEngineManager
import org.apache.jmeter.samplers.SampleResult
import org.apache.jmeter.threads.JMeterVariables

def dir = new File(args[0])
int sessions = args[1] as int
def engine = new ScriptEngineManager().getEngineByName("groovy")
def compiled = [:]
["pick", "start", "next"].each { name ->
    def file = new File(dir, name + ".groovy")
    if (file.exists()) {
        compiled[name] = ((Compilable) engine).compile(file.getText("UTF-8"))
    }
}

def vars = new JMeterVariables()
def prev = new SampleResult()
prev.setSuccessful(true)
prev.setResponseData('{"id": 7}', "UTF-8")
def run = { name ->
    if (compiled[name] == null) {
        return
    }
    def bindings = engine.createBindings()
    bindings.put("vars", vars)
    bindings.put("prev", prev)
    bindings.put("log", null)
    compiled[name].eval(bindings)
}

new File(dir, "walks.jsonl").withWriter("UTF-8") { out ->
    sessions.times {
        run("pick")
        run("start")
        def steps = []
        while (vars.get("stormState") != "END") {
            steps << [vars.get("stormState"), vars.get("stormThinkMs") as long, vars.get("stormIndex") as int]
            run("next")
        }
        out << JsonOutput.toJson([group: vars.get("stormGroup"), steps: steps]) << "\n"
    }
}
