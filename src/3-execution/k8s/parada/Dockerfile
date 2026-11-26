# Servicio de parada (el botón rojo): parada.py + el cliente de Kubernetes para Python.
# Construir:  docker build -t lab-parada src/3-execution/k8s/parada
FROM python:3.12-slim

RUN pip install --no-cache-dir "kubernetes>=31,<40"

WORKDIR /app
COPY parada.py .

# Sin permisos de root: solo escucha en el 8080 y habla con la API de Kubernetes
USER 10001
EXPOSE 8080
CMD ["python", "-u", "parada.py"]