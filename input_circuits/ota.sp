.SUBCKT OTA_5T vin+ vin- vout vdd vss
* Differential Pair
XM1 node_x vin+ node_tail vss nmos_rvt w=270n l=14n nf=2
XM2 vout   vin- node_tail vss nmos_rvt w=270n l=14n nf=2
* Tail Current Source
XM5 node_tail vb1 vss vss nmos_rvt w=540n l=14n nf=4
* Active Load (Current Mirror)
XM3 node_x node_x vdd vdd pmos_rvt w=540n l=14n nf=4
XM4 vout   node_x vdd vdd pmos_rvt w=540n l=14n nf=4
.ENDS