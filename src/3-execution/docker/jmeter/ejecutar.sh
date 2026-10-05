#!/bin/sh
# Uso (desde la carpeta del laboratorio):  docker compose run --rm jmeter <escenario>
# Escenarios disponibles: los ficheros de jmeter/escenarios/*.properties
set -e

ESCENARIO="${1:-humo}"
FICHERO="/tests/escenarios/${ESCENARIO}.properties"

if [ ! -f "$FICHERO" ]; then
  echo "No existe el escenario '${ESCENARIO}'. Disponibles:"
  ls /tests/escenarios | sed 's/\.properties$//'
  exit 1
fi

ID_PRUEBA="${ESCENARIO}-$(date +%Y%m%d-%H%M%S)"
SALIDA="/resultados/${ID_PRUEBA}"
mkdir -p "$SALIDA"

echo "Lanzando escenario '${ESCENARIO}' (id: ${ID_PRUEBA})"
echo "Dashboard en vivo: http://localhost:3001"

jmeter -n \
  -t /tests/plan.jmx \
  -q "$FICHERO" \
  -Jescenario="$ESCENARIO" \
  -Jid_prueba="$ID_PRUEBA" \
  -l "$SALIDA/resultados.jtl" \
  -j "$SALIDA/jmeter.log" \
  -e -o "$SALIDA/informe" \
  $JMETER_ARGS_EXTRA

echo "Terminado. Informe HTML: resultados/${ID_PRUEBA}/informe/index.html"
