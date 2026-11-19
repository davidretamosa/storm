#!/bin/sh
# k3s server en pcb (192.168.10.2), versión fija. Ejecutar en pcb.
# flannel (red entre pods de distintos nodos) va por la interfaz del lab: comprobar su nombre
# con ip -br addr (Hyper-V: eth0; VirtualBox: enp0s3...).
# Después: sudo cat /var/lib/rancher/k3s/server/node-token  (para pcc; NO guardarlo en el repo)
#          kubectl label node pcb rol=controller
#          kubectl label node pcc rol=worker   (cuando pcc se haya unido)
IFACE="${IFACE:-eth0}"
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="v1.37.2+k3s1" \
  INSTALL_K3S_EXEC="server --node-ip 192.168.10.2 --flannel-iface $IFACE --write-kubeconfig-mode 644 --disable traefik --disable servicelb" sh -
