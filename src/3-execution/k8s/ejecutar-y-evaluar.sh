#!/bin/sh
# Se ejecuta DENTRO del pod de JMeter (ver jmeter-job.yaml): lanza la prueba y
# después la evalúa con los criterios de aprobado. Si no los cumple, termina con
# error y el Job queda en estado Failed.
#
# Argumentos: los de jmeter. Variables de entorno:
#   RESULTADOS       carpeta de esta prueba (en el disco jmeter-resultados)
#   MAX_ERRORES_PCT  % máximo de errores que puede tener CADA operación   (criterios/)
#   MAX_P95_MS       el 95 % de todas las peticiones debe responder en menos de esto (ms)
JTL="$RESULTADOS/resultados.jtl"
VEREDICTO="$RESULTADOS/veredicto.txt"
mkdir -p "$RESULTADOS"

# Si el plan no envía métricas a InfluxDB (los generados por 2-processing no lo hacen),
# se ejecuta una copia con el Backend Listener insertado justo después del TestPlan.
PLAN=/test/plan.jmx
if ! grep -q "<BackendListener" "$PLAN"; then
  echo "El plan no envía métricas a Grafana: se añade el Backend Listener (backend-listener.xml)."
  awk -v bloque=/scripts/backend-listener.xml '
    { print }
    tras_testplan && /<hashTree>/ {
      while ((getline linea < bloque) > 0) if (dentro || linea ~ /<BackendListener/) { dentro = 1; print linea }
      tras_testplan = 0
    }
    /<\/TestPlan>/ { tras_testplan = 1 }' "$PLAN" > /tmp/plan.jmx
  # Mismos argumentos, pero con la copia en lugar del plan original
  for arg in "$@"; do
    shift
    [ "$arg" = "$PLAN" ] && arg=/tmp/plan.jmx
    set -- "$@" "$arg"
  done
fi

jmeter "$@" || { echo "JMeter ha terminado con error: no se puede evaluar la prueba."; exit 2; }
[ -s "$JTL" ] || { echo "La prueba no ha generado resultados."; exit 2; }

evaluar() {
  TIEMPOS=/tmp/tiempos.txt
  # El .jtl va separado por tabuladores; las columnas se buscan por nombre en la cabecera
  awk -F'\t' -v max_err="$MAX_ERRORES_PCT" -v tiempos="$TIEMPOS" '
    NR == 1 { for (i = 1; i <= NF; i++) col[$i] = i; next }
    {
      op = $col["label"]; ms = $col["elapsed"]
      n[op]++; total++; suma[op] += ms
      if ($col["success"] != "true") { err[op]++; errores++ }
      print ms > tiempos
    }
    END {
      printf "=== RESULTADO DE LA PRUEBA ===\n"
      printf "%-40s %10s %9s %10s\n", "Operación", "Peticiones", "Errores", "Media"
      for (op in n) {
        pct = 100 * err[op] / n[op]
        printf "%-40s %10d %8.2f%% %8.0f ms%s\n", op, n[op], pct, suma[op] / n[op], (pct > max_err ? "  <-- supera el límite" : "")
        if (pct > peor_pct) { peor_pct = pct; peor_op = op }
      }
      printf "%-40s %10d %8.2f%%\n", "TOTAL", total, 100 * errores / total
      # Para el veredicto: peor % de errores y la operación que lo tiene
      printf "%.4f|%s\n", peor_pct, peor_op > "/tmp/peor.txt"
    }' "$JTL"

  P95=$(sort -n "$TIEMPOS" | awk '{ v[NR] = $1 } END { i = int(NR * 0.95 + 0.5); if (i < 1) i = 1; print v[i] }')
  PEOR_PCT=$(cut -d'|' -f1 /tmp/peor.txt)
  PEOR_OP=$(cut -d'|' -f2 /tmp/peor.txt)

  echo
  echo "=== CRITERIOS DE APROBADO ==="
  SUPERADA=si
  if awk -v a="$PEOR_PCT" -v b="$MAX_ERRORES_PCT" 'BEGIN { exit !(a <= b) }'; then
    printf "[OK]    Errores: ninguna operación pasa del %s %% (la peor: %.2f %%)\n" "$MAX_ERRORES_PCT" "$PEOR_PCT"
  else
    printf "[FALLO] Errores: \"%s\" tiene un %.2f %%, el máximo es %s %%\n" "$PEOR_OP" "$PEOR_PCT" "$MAX_ERRORES_PCT"
    SUPERADA=no
  fi
  if [ "$P95" -le "$MAX_P95_MS" ]; then
    echo "[OK]    Tiempo: el 95 % de las peticiones responde en ${P95} ms o menos (máximo ${MAX_P95_MS} ms)"
  else
    echo "[FALLO] Tiempo: el 95 % de las peticiones tarda hasta ${P95} ms, el máximo es ${MAX_P95_MS} ms"
    SUPERADA=no
  fi

  echo
  if [ "$SUPERADA" = si ]; then
    echo "VEREDICTO: PRUEBA SUPERADA"
  else
    echo "VEREDICTO: PRUEBA NO SUPERADA"
  fi
}

# La evaluación se guarda junto a los resultados y se muestra en el log del pod
evaluar > "$VEREDICTO"
echo
cat "$VEREDICTO"
grep -q "VEREDICTO: PRUEBA SUPERADA" "$VEREDICTO"
