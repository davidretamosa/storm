#!/bin/sh
# k3s agent en pcc (192.168.10.3), misma versión que el server. Ejecutar en pcc:
#   K3S_TOKEN=<token de pcb> ./k3s-agent-pcc.sh
# El token sale en pcb con: sudo cat /var/lib/rancher/k3s/server/node-token
IFACE="${IFACE:-eth0}"
: "${K3S_TOKEN:?Falta K3S_TOKEN (sudo cat /var/lib/rancher/k3s/server/node-token en pcb)}"
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="v1.37.2+k3s1" K3S_URL="https://192.168.10.2:6443" \
  K3S_TOKEN="$K3S_TOKEN" INSTALL_K3S_EXEC="agent --node-ip 192.168.10.3 --flannel-iface $IFACE" sh -
