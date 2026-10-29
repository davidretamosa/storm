#!/bin/sh
# Borra todo el laboratorio del clúster, discos incluidos: se pierden los datos de InfluxDB,
# Prometheus y los resultados guardados en el clúster (no los copiados en resultados/).
# Uso, desde src/3-execution/k8s:  ./quitar.sh
kubectl delete namespace lab-jmeter --ignore-not-found
# Los permisos de Prometheus son de todo el clúster y no se borran con el namespace
kubectl delete clusterrolebinding lab-jmeter-prometheus --ignore-not-found
kubectl delete clusterrole lab-jmeter-prometheus --ignore-not-found
