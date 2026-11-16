import org.apache.jmeter.protocol.http.control.Header
import org.apache.jmeter.protocol.http.control.HeaderManager

// Recuperar las cabeceras seleccionadas para la petición
def headers = vars.getObject("stormHeaders") ?: [:]

// Recuperar el gestor de cabeceras del sampler
def manager = sampler.getHeaderManager()

if (manager == null) {
    manager = new HeaderManager()
    sampler.setHeaderManager(manager)
}

// Eliminar las cabeceras dinámicas de la ejecución anterior
def previousHeaders = vars.getObject("stormPreviousHeaders") ?: []

previousHeaders.each { name ->
    manager.removeHeaderNamed(name)
}

// Añadir las cabeceras seleccionadas
headers.each { name, values ->
    manager.removeHeaderNamed(name)

    values.each { value ->
        manager.add(new Header(
            name.toString(),
            value.toString()
        ))
    }
}

// Guardar los nombres para la siguiente petición
vars.putObject(
    "stormPreviousHeaders",
    headers.keySet().toList()
)