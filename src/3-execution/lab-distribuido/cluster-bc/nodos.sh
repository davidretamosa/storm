#!/bin/sh
# Muestra los nodos de inyección (label rol=worker) y los recursos que les quedan libres para
# los workers de JMeter. "Libre" = lo que el nodo ofrece a los pods (allocatable) menos lo que ya
# tienen RESERVADO (requests) los pods que corren en él: Kubernetes coloca los pods según las
# reservas, no según el consumo real, así que un worker solo cabe si pide como mucho esto.
#
# Uso, en pcb desde lab-distribuido/cluster-bc:
#   ./nodos.sh            tabla para leer
#   ./nodos.sh --datos    una línea por nodo: nombre cpu_total cpu_libre ram_total_mi ram_libre_mi
#                         (CPU en cores, RAM en MiB). Lo usan desplegar.sh y dimensionar.sh.
# Muestra TODO lo libre: cuánto se da a los workers lo decide quien lanza la prueba
# (desplegar.sh --worker-ram / --worker-cpu).
set -e
export MSYS_NO_PATHCONV=1
DATOS=no
case "$1" in
  --datos) DATOS=si ;;
  '')      ;;
  *)       echo "Uso: ./nodos.sh [--datos]"; exit 1 ;;
esac

NODOS=$(kubectl get nodes -l rol=worker -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
if [ -z "$NODOS" ]; then
  echo "Ningún nodo tiene la label rol=worker: kubectl label node <nodo> rol=worker" >&2
  exit 1
fi

# Pasa cantidades de Kubernetes a cores (cpu) o MiB (memoria): 250m, 2, 1.5 / 768Mi, 3Gi, 4026532Ki, 3G...
A_NUMEROS='
function cpu(v) { if (v == "") return 0; if (v ~ /m$/) return substr(v, 1, length(v) - 1) / 1000; return v + 0 }
function mem(v,  n) {
  if (v == "") return 0
  n = v + 0
  if (v ~ /Ki$/) return n / 1024
  if (v ~ /Mi$/) return n
  if (v ~ /Gi$/) return n * 1024
  if (v ~ /Ti$/) return n * 1024 * 1024
  if (v ~ /k$/)  return n * 1000 / 1048576
  if (v ~ /M$/)  return n * 1000000 / 1048576
  if (v ~ /G$/)  return n * 1000000000 / 1048576
  return n / 1048576
}'

for NODO in $NODOS; do
  ASIGNABLE=$(kubectl get node "$NODO" -o jsonpath='{.status.allocatable.cpu} {.status.allocatable.memory}')
  # Reservas (requests) de cada contenedor de los pods vivos del nodo: "cpu|memoria" por línea
  # (separadas por | porque un contenedor puede reservar solo una de las dos)
  RESERVAS=$(kubectl get pods -A --field-selector "spec.nodeName=$NODO,status.phase!=Succeeded,status.phase!=Failed" \
    -o jsonpath='{range .items[*].spec.containers[*]}{.resources.requests.cpu}|{.resources.requests.memory}{"\n"}{end}')
  printf '%s\n' "$RESERVAS" | awk -F'|' -v nodo="$NODO" -v asignable="$ASIGNABLE" "$A_NUMEROS"'
    NF { cpu_res += cpu($1); mem_res += mem($2) }
    END {
      split(asignable, a, " ")
      cpu_tot = cpu(a[1]); mem_tot = mem(a[2])
      cpu_lib = cpu_tot - cpu_res; mem_lib = mem_tot - mem_res
      if (cpu_lib < 0) cpu_lib = 0
      if (mem_lib < 0) mem_lib = 0
      printf "%s %.2f %.2f %d %d\n", nodo, cpu_tot, cpu_lib, mem_tot, mem_lib
    }'
done > /tmp/nodos.$$

if [ "$DATOS" = si ]; then
  cat /tmp/nodos.$$
else
  echo "=== NODOS DE INYECCIÓN (rol=worker) ==="
  awk '
    BEGIN { printf "%-12s %10s %11s %11s %12s\n", "Nodo", "CPU total", "CPU libre", "RAM total", "RAM libre" }
    { printf "%-12s %10.1f %11.1f %8.1f GB %9.1f GB\n", $1, $2, $3, $4 / 1024, $5 / 1024
      c += $3; m += $5 }
    END { printf "%-12s %10s %11.1f %11s %9.1f GB\n", "TOTAL", "", c, "", m / 1024 }' /tmp/nodos.$$
fi
rm -f /tmp/nodos.$$
