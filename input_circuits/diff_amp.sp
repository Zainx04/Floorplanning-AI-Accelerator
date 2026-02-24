* Simple 5-Transistor OTA (Differential Pair with Current Mirror Load)
* Topology: PMOS current mirror load + NMOS diff pair + NMOS tail current source
*
* Ports: inp inn vout ibias vdd vss
*   inp/inn  : differential inputs
*   vout     : single-ended output
*   ibias    : bias voltage for tail current source
*   vdd/vss  : supply rails

.subckt diff_amp inp inn vout ibias vdd vss
* PMOS current mirror load (matched pair)
mp1 vout  vout vdd vdd pmos_rvt w=540e-9 l=20e-9 nfin=8 nf=2
mp2 net1  vout vdd vdd pmos_rvt w=540e-9 l=20e-9 nfin=8 nf=2
* NMOS differential input pair (matched pair)
mn1 vout  inp  tail vss nmos_rvt w=540e-9 l=20e-9 nfin=8 nf=2
mn2 net1  inn  tail vss nmos_rvt w=540e-9 l=20e-9 nfin=8 nf=2
* NMOS tail current source (single device, no match needed)
mn3 tail  ibias vss vss nmos_rvt w=270e-9 l=20e-9 nfin=4 nf=2
.ends diff_amp
