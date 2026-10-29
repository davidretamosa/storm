"""Trànsit habitual (T-1): la corba horària, del log al .jmx.

- concurrency_curve(df): quantes sessions hi havia obertes a cada franja del log, en proporció a la franja
  més plena (1 = la més plena). Sessió = de la primera petició a l'última, com peak_concurrent_sessions.
- timer(curve): un JSR223Timer (Groovy estàndard de JMeter 5.6.3) que, a l'inici de cada sessió simulada,
  fa esperar els fils que en aquell moment no toca que treballin.

La corba va APAGADA per defecte (Addenda 1 de l'encàrrec T-1): sense -Jcurva_horaria=1, el temporitzador
torna 0 i el pla fa el pic constant de sempre, que és el que fan servir els escenaris del laboratori.
"""
import math
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from ai import jmx_post

PROPERTY = "curva_horaria"
SLICE_SECONDS = 600     # franges d'uns 10 minuts del log (ajustades perquè el cobreixin just)
MAX_SLICES = 288        # 2 dies de log; si n'és més, les franges s'eixamplen
MIN_SESSION_SECONDS = 1  # una sessió d'una sola petició compta com si durés 1 s (si no, no pesaria gens)
TIMER_NAME = "STORM-IA: curva horaria"

# Groovy dins del .jmx: en castellà, com la resta del pla (el llegeix el laboratori)
SCRIPT = """// STORM-IA (T-1) · curva horaria del log. Apagada salvo que se lance con -J%(property)s=1 (otro valor: apagada).
// Encendida: el log entero se comprime en la duración de la prueba (duration) y, en cada franja, solo
// trabajan tantos hilos como sesiones abiertas tenía el log, en proporción a la franja más llena (que
// tiene todos los hilos: el pico sigue siendo vusers). Un hilo al que no le toca espera hasta la primera
// franja en la que le toca, o acaba si ya no le toca ninguna. Una sesión empezada no se corta.
// Devuelve la espera en ms.
import java.util.concurrent.ThreadLocalRandom
import org.apache.jmeter.threads.JMeterContextService

if (props.getProperty("%(property)s", "0").trim() != "1") {
    return 0L
}
double[] curve = [%(values)s] as double[]
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
"""


def concurrency_curve(df, slice_seconds=SLICE_SECONDS, max_slices=MAX_SLICES):
    """{"start": hora de la primera franja, "slice_seconds": s, "values": [0.34, ..., 1.0, ...]} o None.

    values[j] = sessions obertes de mitjana a la franja j (ponderat pel temps) / la de la franja més plena.
    None si el log no té sessions: sense corba, el temporitzador no s'afegeix.
    """
    if df is None or df.empty or "session_id" not in df.columns:
        return None
    sessions = df.dropna(subset=["session_id"]).groupby("session_id")["timestamp"].agg(["min", "max"])
    if sessions.empty:
        return None

    first = sessions["min"].min()
    starts = (sessions["min"] - first).dt.total_seconds().to_numpy()
    ends = np.maximum((sessions["max"] - first).dt.total_seconds().to_numpy(), starts + MIN_SESSION_SECONDS)

    # Franges iguals que cobreixen el log just (~slice_seconds cadascuna): una última franja mig buida faria
    # adormir els fils a la part de la prova que li toca, com si el log s'hi hagués quedat sense sessions
    span = ends.max()
    count = min(max_slices, max(1, math.ceil(span / slice_seconds)))
    slice_seconds = span / count
    edges = np.arange(count + 1) * slice_seconds

    # Segons que cada sessió és oberta dins de cada franja (sessions x franges), sumats per franja
    overlap = np.minimum(ends[:, None], edges[None, 1:]) - np.maximum(starts[:, None], edges[None, :-1])
    open_sessions = np.clip(overlap, 0, None).sum(axis=0) / slice_seconds
    values = open_sessions / open_sessions.max()
    return {
        "start": pd.Timestamp(first).isoformat(),
        "slice_seconds": float(slice_seconds),
        "values": [round(float(v), 4) for v in values],
    }


def timer(curve):
    """(<JSR223Timer>, <hashTree/>) amb la corba dins del script."""
    element = ET.Element("JSR223Timer", {"guiclass": "TestBeanGUI", "testclass": "JSR223Timer",
                                         "testname": TIMER_NAME})
    element.append(jmx_post.string_prop("scriptLanguage", "groovy"))
    element.append(jmx_post.string_prop("parameters", ""))
    element.append(jmx_post.string_prop("filename", ""))
    element.append(jmx_post.string_prop("cacheKey", "true"))
    values = ", ".join(repr(v) for v in curve["values"])
    element.append(jmx_post.string_prop("script", SCRIPT % {"property": PROPERTY, "values": values}))
    return element, ET.Element("hashTree")


def add_timer(root, curve):
    """Posa el temporitzador a «Nueva sesión» (el TestAction amb què comença cada sessió del pla dels companys),
    darrere del que ja hi ha. Si el pla ja no té aquest TestAction, falla: millor que una corba que no actua."""
    thread_group = root.find(".//ThreadGroup")
    if thread_group is None:
        raise ValueError("el .jmx no té ThreadGroup: la corba horària no es pot posar")
    actions = [child for child in jmx_post.child_tree(root, thread_group) if child.tag == "TestAction"]
    if len(actions) != 1:
        raise ValueError(f"s'esperava un TestAction d'inici de sessió i n'hi ha {len(actions)}")
    children = jmx_post.child_tree(root, actions[0])
    children.extend(timer(curve))
