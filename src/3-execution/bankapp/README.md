# Bankapp en el laboratorio

Compila la aplicación objetivo del proyecto (`src/1-input/java-app-mock`) para desplegarla en
el laboratorio de Kubernetes (`../k8s`), donde se le inyecta el plan del grupo de IA.

| Fichero | Qué es |
|---|---|
| `construir-imagen.sh` | Compila la bankapp desde una rama de Git y crea la imagen `bankapp` |
| `Dockerfile` | Compilación con Maven dentro de Docker (no hace falta Java en el equipo) |

## Uso

```bash
./construir-imagen.sh                      # código de origin/develop (por defecto)
./construir-imagen.sh origin/feature/java-app   # o el de otra rama
../k8s/desplegar.sh                        # despliega la bankapp junto al resto del laboratorio
```

Cada vez que se despliega, la bankapp arranca con los datos iniciales de su `data.sql`
(usuarios y cuentas 1 a 3).
