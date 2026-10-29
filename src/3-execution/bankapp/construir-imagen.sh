#!/bin/sh
# Construye la imagen Docker "bankapp" a partir del código de src/1-input/java-app-mock.
# Uso, desde src/3-execution/bankapp:  ./construir-imagen.sh [rama]
#
# El código se toma de una rama de Git sin cambiar de rama ni copiar nada:
# por defecto origin/develop. Para probar otra versión: ./construir-imagen.sh origin/feature/java-app
set -e
cd "$(dirname "$0")"
RAMA="${1:-origin/develop}"
CODIGO=src/1-input/java-app-mock

git fetch -q origin
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git -C "$(git rev-parse --show-toplevel)" archive "$RAMA" "$CODIGO" | tar -x -C "$TMP"

echo "Construyendo la imagen bankapp con el código de $RAMA ($(git log -1 --format='%h, %ad' --date=short "$RAMA"))..."
docker build -q -t bankapp:latest -f Dockerfile "$TMP/$CODIGO" >/dev/null
echo "Imagen bankapp lista. Despliégala con: ../k8s/desplegar.sh"
