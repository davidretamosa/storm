#!/bin/sh
# Borra lo de PC A (bankapp y Prometheus), disco de Prometheus incluido.
# Uso, en PC A desde lab-distribuido/pc-a:  ./quitar.sh
kubectl delete namespace lab-jmeter --ignore-not-found
# Los permisos de Prometheus son de todo el clúster y no se borran con el namespace
kubectl delete clusterrolebinding lab-jmeter-prometheus --ignore-not-found
kubectl delete clusterrole lab-jmeter-prometheus --ignore-not-found
