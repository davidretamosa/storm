# Imagen del generador de planes de 2-processing (src/2-processing, de David).
# Se construye con ./construir-imagen.sh, que toma el código de su rama de Git.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
# pytest solo hace falta para sus tests, no para generar planes
RUN grep -v pytest requirements.txt > req.txt && pip install --no-cache-dir -r req.txt
COPY . .
ENTRYPOINT ["python", "main.py"]
