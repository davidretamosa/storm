#!/bin/sh
# Borra todo el laboratorio del clúster (los datos de InfluxDB y Prometheus se pierden).
# Uso, desde src/3-execution/k8s:  ./quitar.sh
kubectl delete namespace lab-jmeter --ignore-not-found
# Los permisos de Prometheus son de todo el clúster y no se borran con el namespace
kubectl delete clusterrolebinding lab-jmeter-prometheus --ignore-not-found
kubectl delete clusterrole lab-jmeter-prometheus --ignore-not-found
