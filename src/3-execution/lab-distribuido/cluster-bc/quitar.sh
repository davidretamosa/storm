#!/bin/sh
# Borra el clúster 1 del lab distribuido, discos incluidos: se pierden los datos de InfluxDB
# y los resultados guardados en el clúster (no los copiados en resultados/).
# Uso, en pcb desde lab-distribuido/cluster-bc:  ./quitar.sh
kubectl delete namespace lab-jmeter --ignore-not-found
