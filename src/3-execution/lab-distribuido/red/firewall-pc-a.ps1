# Firewall de Windows en PC A: deja entrar desde la red del lab (192.168.10.0/24)
# el ping y los NodePorts de la bankapp (30081) y Prometheus (30090).
# PowerShell como administrador. Se puede repetir: borra antes las reglas "STORM lab".
# (Los puertos de k3s 6443/tcp, 10250/tcp y 8472/udp son entre pcb y pcc: el firewall de
#  Ubuntu viene apagado y el de Windows no filtra el tráfico de las VMs, así que no hacen falta aquí.)
Remove-NetFirewallRule -DisplayName "STORM lab*" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "STORM lab - ping" -Direction Inbound -Protocol ICMPv4 -IcmpType 8 -RemoteAddress 192.168.10.0/24 -Action Allow
New-NetFirewallRule -DisplayName "STORM lab - bankapp y Prometheus" -Direction Inbound -Protocol TCP -LocalPort 30081,30090 -RemoteAddress 192.168.10.0/24 -Action Allow
# Si alguna vez se pulsó "Cancelar" en el aviso del firewall al instalar Docker Desktop, Windows
# crea reglas que BLOQUEAN com.docker.backend.exe (el que atiende los NodePorts) en redes Públicas,
# y un bloqueo gana a cualquier permiso: se desactivan (Enable-NetFirewallRule para deshacerlo).
Get-NetFirewallRule -DisplayName "com.docker.backend.exe" -ErrorAction SilentlyContinue |
  Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' } | Disable-NetFirewallRule
