# Crea el conmutador del lab, la IP de Windows (PC A) y las VMs pcb y pcc en Hyper-V.
# PowerShell como administrador. Ajustar $DIR y $ISO.
# En PCs físicos: conmutador EXTERNO vinculado a la Ethernet (New-VMSwitch -NetAdapterName ...)
# y cada PC crea solo su VM; en PC A la IP 192.168.10.1 va en su tarjeta Ethernet.
$DIR = "C:\Users\Iria\labD\VMs"
$ISO = "$DIR\ubuntu-26.04.1-live-server-amd64.iso"

New-VMSwitch -Name "lab-storm" -SwitchType Internal
New-NetIPAddress -InterfaceAlias "vEthernet (lab-storm)" -IPAddress 192.168.10.1 -PrefixLength 24

foreach ($vm in @(@{N="pcb"; M=4GB; D=30GB}, @{N="pcc"; M=3GB; D=25GB})) {
  $n = $vm.N
  New-Item -ItemType Directory -Force "$DIR\$n" | Out-Null
  New-VM -Name $n -Generation 2 -MemoryStartupBytes $vm.M -Path $DIR -NewVHDPath "$DIR\$n\$n.vhdx" -NewVHDSizeBytes $vm.D -SwitchName "lab-storm"
  Set-VMMemory -VMName $n -DynamicMemoryEnabled $false
  Set-VMProcessor -VMName $n -Count 2
  Set-VM -Name $n -AutomaticCheckpointsEnabled $false
  Rename-VMNetworkAdapter -VMName $n -NewName "lab"
  Add-VMNetworkAdapter -VMName $n -Name "internet" -SwitchName "Default Switch"
  Add-VMDvdDrive -VMName $n -Path $ISO
  Set-VMFirmware -VMName $n -SecureBootTemplate MicrosoftUEFICertificateAuthority -FirstBootDevice (Get-VMDvdDrive -VMName $n)
}
