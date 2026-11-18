// STORM-IA (tráfico habitual, T-1.4): curva horaria del log. Apagada salvo que se lance con
// -Jcurva_horaria=1 (cualquier otro valor, o ninguno: apagada, y el plan hace el pico constante de siempre).
// Encendida: el log entero se comprime en la duración de la prueba (duration) y, en cada franja, solo
// trabajan tantos hilos como sesiones abiertas tenía el log, en proporción a la franja más llena (que
// tiene todos los hilos: el pico sigue siendo vusers). Un hilo al que no le toca espera hasta la primera
// franja en la que le toca, o acaba si ya no le toca ninguna. Una sesión empezada no se corta.
// Devuelve la espera en ms.
import java.util.concurrent.ThreadLocalRandom
import org.apache.jmeter.threads.JMeterContextService

if (props.getProperty("curva_horaria", "0").trim() != "1") {
    return 0L
}
double[] curve = [__CURVE_VALUES__] as double[]
def group = ctx.getThreadGroup()
long durationMs = group.getDuration() * 1000L
if (durationMs <= 0) {
    return 0L   // sin duración no hay a qué comprimir el log
}
int threads = group.getNumThreads()
int me = ctx.getThreadNum()
double sliceMs = durationMs / (double) curve.length
long elapsed = System.currentTimeMillis() - JMeterContextService.getTestStartTime()

for (int j = Math.max(0, (int) (elapsed / sliceMs)); j < curve.length; j++) {
    double target = curve[j] * threads
    int whole = (int) Math.floor(target)
    boolean works = me < whole || (me == whole && ThreadLocalRandom.current().nextDouble() < target - whole)
    if (works) {
        return Math.max(0L, (long) (j * sliceMs) - elapsed)
    }
}
// Ya no le toca: el hilo acaba aquí. Esperar al final no sirve: JMeter recorta la espera al final de la
// prueba y el hilo aún empezaría una última sesión (todos a la vez).
ctx.getThread().stop()
return 0L
