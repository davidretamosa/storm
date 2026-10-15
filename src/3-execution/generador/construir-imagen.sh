#!/bin/sh
# Construye la imagen "storm-generador" con el generador de planes de 2-processing.
# Uso, desde src/3-execution/generador:  ./construir-imagen.sh [rama]
#
# El código se toma de una rama de Git sin cambiar de rama ni copiar nada:
# por defecto origin/feature/processing (la de David). Cuando esté en develop:
# ./construir-imagen.sh origin/develop
set -e
cd "$(dirname "$0")"
RAMA="${1:-origin/feature/processing}"
CODIGO=src/2-processing

git fetch -q origin
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git -C "$(git rev-parse --show-toplevel)" archive "$RAMA" "$CODIGO" | tar -x -C "$TMP"

echo "Construyendo la imagen storm-generador con el código de $RAMA ($(git log -1 --format='%h, %ad' --date=short "$RAMA"))..."
docker build -q -t storm-generador:latest -f Dockerfile "$TMP/$CODIGO" >/dev/null
echo "Imagen storm-generador lista. Genera un plan con: ../k8s/generar-plan.sh"
