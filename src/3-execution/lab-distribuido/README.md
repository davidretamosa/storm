# Lab distribuido de STORM (3-execution)

Laboratorio de pruebas de carga con JMeter repartido en **dos clústeres de Kubernetes**:

- **Clúster 1** (k3s, 2 nodos): genera la carga. JMeter master, InfluxDB y Grafana en **pcb**;
  el worker de JMeter en **pcc**.
- **PC A** (Kubernetes de Docker Desktop, 1 nodo): la app que se pone a prueba (**bankapp**) y
  **Prometheus**, que mide su CPU y memoria. Simula la app de CaixaBank, fuera del clúster que inyecta.

```
           red del lab 192.168.10.0/24 (sin gateway; internet va por otra interfaz)
  ┌────────────────────────┬───────────────────────────┬──────────────────────────┐
  │ PC A  192.168.10.1     │ pcb  192.168.10.2         │ pcc  192.168.10.3        │
  │ Docker Desktop K8s     │ k3s server, rol=controller│ k3s agent, rol=worker    │
  │  bankapp   :30081 ◄────┼── JMeter master (Job)     │                          │
  │  Prometheus:30090 ◄──┐ │  InfluxDB                 │                          │
  │                      └─┼─ Grafana :30000           │                          │
  │            ◄───────────┼───────────────────────────┼── JMeter worker (carga)  │
  └────────────────────────┴───────────────────────────┴──────────────────────────┘
```

El master (pcb) reparte el plan entre los workers (pcc) por RMI; los workers atacan la bankapp
en `192.168.10.1:30081` y mandan métricas a InfluxDB; Grafana lee InfluxDB (JMeter) y el
Prometheus de PC A (`192.168.10.1:30090`, CPU y memoria de la bankapp).

## Estructura

| Carpeta | Dónde se ejecuta | Qué hay |
|---|---|---|
| `red/` | Windows / pcb / pcc | Hyper-V (conmutador y VMs), netplan de pcb y pcc, instalación de k3s, firewall de PC A |
| `cluster-bc/` | **pcb** | Despliegue del clúster 1 y pruebas: scripts, yaml, `grafana/`, `escenarios/`, `criterios/` |
| `pc-a/` | **PC A** (Git Bash) | Despliegue de la bankapp y Prometheus |

Fuera de esta carpeta solo se usa: `src/3-execution/bankapp/` (receta de la imagen de la bankapp,
la construye GitHub Actions), `src/1-input/java-app-mock/logs/bankapp.jsonl` (logs) y
`src/2-processing/` (genera el plan `.jmx`).

## Versiones (fijas, para que la demo funcione sin internet)

| Componente | Versión |
|---|---|
| Ubuntu Server (pcb, pcc) | 26.04.1 LTS |
| k3s | v1.37.2+k3s1 (sin traefik ni servicelb) |
| Imágenes storm (`ghcr.io/davidretamosa/storm-bankapp`, `storm-lab-jmeter`) | `sha-d1f458f` (develop, 13/11/2026). Recetas: `src/3-execution/bankapp/Dockerfile` y `src/3-execution/lab-jmeter/jmeter/Dockerfile`, publicadas por `.github/workflows/imagenes.yml` |
| Grafana / InfluxDB / Prometheus / busybox | 11.3.0 / 1.8.10 / v2.53.0 / 1.36 |
| Docker Desktop Kubernetes (PC A) | v1.36.1 |

Todas las imágenes usan `imagePullPolicy: IfNotPresent`: si ya están en la máquina, no se descargan.
Otra versión de las de storm: `ETIQUETA=sha-xxxxxxx ./desplegar.sh` (en `pc-a/` y `cluster-bc/`).

## Montarlo (fase actual: todo en un PC con Windows 11 Pro)

Windows hace de PC A; pcb y pcc son VMs de Hyper-V (pcb 4 GB y pcc 3 GB de RAM, 2 CPU; Docker
limitado a 5 GB con `%USERPROFILE%\.wslconfig` → `[wsl2]` `memory=5GB`).

1. **Hyper-V** (PowerShell admin): `Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All` y reiniciar.
2. **Conmutador, IP de Windows y VMs**: `red/hyperv-crear-red-y-vms.ps1` (ajustar `$DIR` y `$ISO`).
   Cada VM: adaptador `lab` (conmutador interno `lab-storm`) y `internet` (`Default Switch`, NAT).
3. **Ubuntu Server** en cada VM: hostname `pcb` / `pcc`, sin LVM, con OpenSSH. En Hyper-V,
   `eth0` = lab y `eth1` = internet (comprobar con `ip -br addr`).
4. **IP fija** en cada VM: `red/netplan-pcb.yaml` / `red/netplan-pcc.yaml` en `/etc/netplan/60-lab.yaml`
   (instrucciones dentro). Al aplicarlo se corta el SSH por la IP 172.x: volver a entrar por la fija.
5. **Firewall de PC A** (PowerShell admin):
   `powershell -ExecutionPolicy Bypass -File red\firewall-pc-a.ps1` (ping, 30081, 30090 y desbloqueo de Docker).
   Comprobar: `ping` entre .1, .2 y .3 en todos los sentidos.
6. **k3s**: en pcb `red/k3s-server-pcb.sh`; en pcc `K3S_TOKEN=<token> red/k3s-agent-pcc.sh`
   (token: `sudo cat /var/lib/rancher/k3s/server/node-token` en pcb; **no guardarlo en el repo**). En pcb:
   `kubectl label node pcb rol=controller` y `kubectl label node pcc rol=worker`.
   Comprobar: `kubectl get nodes -L rol -o wide` (los dos `Ready`, con sus IPs del lab).
7. **PC A** (Git Bash): `kubectl config use-context docker-desktop` y `pc-a/desplegar.sh`.
   Comprobar desde pcb: `curl http://192.168.10.1:30081/actuator/health/readiness` → `{"status":"UP"}`
   y `curl http://192.168.10.1:30090/-/ready`.
8. **Clúster 1**: copiar esta carpeta a pcb (`scp -r ... iria@192.168.10.2:~/`, luego
   `chmod +x ~/lab-distribuido/cluster-bc/*.sh`) y en pcb `cluster-bc/desplegar.sh`.
   Comprobar: `kubectl -n lab-jmeter get pods -o wide` (grafana, influxdb y resultados en pcb) y
   Grafana en `http://192.168.10.2:30000/d/lab-jmeter-k8s` (admin / admin).

## Lanzar una prueba

```bash
# En Windows (raíz del repo): .jar de la imagen y plan con 2-processing (entrada/ no se sube)
mkdir -p entrada
docker create --name bankapp-jar ghcr.io/davidretamosa/storm-bankapp:sha-d1f458f
MSYS_NO_PATHCONV=1 docker cp bankapp-jar:/app/app.jar entrada/bankapp.jar && docker rm bankapp-jar
cd src/2-processing     # la primera vez: py -3 -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe main.py --jar ../../entrada/bankapp.jar \
  --logs ../1-input/java-app-mock/logs/bankapp.jsonl --session --output ../../entrada/plan.jmx
# Copiarlo a pcb (PowerShell): scp entrada\plan.jmx iria@192.168.10.2:~/plan.jmx

# En pcb, desde ~/lab-distribuido/cluster-bc
./cargar-plan.sh ~/plan.jmx
./lanzar-prueba.sh humo externo --workers 1
./lanzar-prueba.sh normal externo --workers 1
```

## Demo sin internet

Las imágenes se descargan la primera vez que se usan en cada máquina; después basta con `IfNotPresent`.
Antes de la demo, con internet: desplegar todo y lanzar al menos una prueba con `--workers 1`
(así pcb tiene la imagen de JMeter del master y pcc la del worker). Comprobar con
`sudo k3s crictl images` en pcb y pcc y `docker images` en PC A. Ensayo: apagar el wifi y repetir
una prueba completa.

## Pasar a PCs físicos

- Red: switch con cables, IPs fijas 192.168.10.x **sin gateway**; cada PC con su wifi para internet.
- PC A: sin VMs; la IP 192.168.10.1 en su tarjeta Ethernet; Docker Desktop con Kubernetes,
  `red/firewall-pc-a.ps1` y `pc-a/desplegar.sh`.
- PC de pcb y PC de pcc: cada uno con su VM. Hyper-V con conmutador **externo** vinculado a la
  Ethernet (VirtualBox: adaptador puente). La interfaz puede no llamarse `eth0`: ajustar netplan
  y `IFACE=... red/k3s-*.sh`.
- k3s entre pcb y pcc usa 6443/tcp, 10250/tcp y 8472/udp. El firewall de Ubuntu viene apagado y el de
  Windows no filtra el tráfico de las VMs con conmutador externo/puente, así que no hay que abrir nada.

## Origen de los ficheros

Copiados de **develop @ `0851916`** ("Añade escenarios lento, moderado y rapido") y adaptados:

| Copia | Original |
|---|---|
| `cluster-bc/*.yaml`, `*.sh`, `backend-listener.xml`, `escenarios/`, `criterios/objetivo.properties`, `grafana/lab-jmeter-k8s.json` | `src/3-execution/k8s/` (mismo nombre) |
| `cluster-bc/grafana/datasources.yml`, `dashboards.yml` | `src/3-execution/lab-jmeter/grafana/provisioning/` |
| `pc-a/desplegar.sh` | `src/3-execution/k8s/desplegar-objetivo.sh` |
| `pc-a/objetivo.yaml`, `prometheus.yaml`, `almacenamiento.yaml`, `00-namespace.yaml`, `quitar.sh` | `src/3-execution/k8s/` |

## Pendiente

- Botón rojo (`feature/3-execution-red-button-proxy`) y escenarios nuevos (carga indefinida), cuando lleguen a develop.
- Réplicas de la bankapp (HPA + metrics-server en PC A).
