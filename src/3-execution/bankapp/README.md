# Bankapp: la app de ejemplo del proyecto

STORM sirve para cualquier aplicación: en el laboratorio de Kubernetes (`../k8s`) la app que se
pone a prueba es la **app objetivo**, que se despliega con `../k8s/desplegar-objetivo.sh` a
partir de su imagen o de su `.jar`. La bankapp (`src/1-input/java-app-mock`) es la app de ejemplo
que ha hecho el equipo para probarlo de punta a punta.

| Fichero | Qué es |
|---|---|
| `construir-imagen.sh` | Compila la bankapp desde una rama de Git y crea la imagen `bankapp` en este equipo |
| `Dockerfile` | Compilación con Maven dentro de Docker (no hace falta Java en el equipo) |

## Uso

Con la imagen que publica GitHub Actions (no hace falta compilar nada):

```bash
../k8s/desplegar-objetivo.sh --imagen ghcr.io/davidretamosa/storm-bankapp --salud /actuator/health/readiness
```

O compilándola en el equipo (por ejemplo, para probar el código de otra rama):

```bash
./construir-imagen.sh                           # código de origin/develop (por defecto)
./construir-imagen.sh origin/feature/java-app   # o el de otra rama
../k8s/desplegar-objetivo.sh --imagen bankapp:latest --salud /actuator/health/readiness
```

`--salud` usa el endpoint de Spring Boot que dice cuándo está lista. Cada vez que se despliega,
la bankapp arranca con los datos iniciales de su `data.sql` (usuarios y cuentas 1 a 3).
