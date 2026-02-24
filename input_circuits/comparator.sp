.SUBCKT CLOCKED_COMPARATOR INP INN CLK CLK_DLY OUTP OUTN VDD VSS
* --- Stage 1: Preamplifier (Left Side) ---
* Tail NMOS
XM_TAIL1 VGND1 CLK VSS VSS nmos_rvt w=540n l=14n nf=2
* Input Differential Pair
XM_DP1 OUTN INP VGND1 VSS nmos_rvt w=540n l=14n nf=2
XM_DP2 OUTP INN VGND1 VSS nmos_rvt w=540n l=14n nf=2
* PMOS Active Loads (Gates tied to VSS to stay ON)
XM_LOAD1 OUTN VSS VDD VDD pmos_rvt w=270n l=14n nf=2
XM_LOAD2 OUTP VSS VDD VDD pmos_rvt w=270n l=14n nf=2

* --- Stage 2: Cross-Coupled Latch (Right Side) ---
* Latch Tail NMOS
XM_TAIL2 VGND2 CLK_DLY VSS VSS nmos_rvt w=540n l=14n nf=2
* Cross-Coupled NMOS
XM_N1 OUTP OUTN VGND2 VSS nmos_rvt w=540n l=14n nf=2
XM_N2 OUTN OUTP VGND2 VSS nmos_rvt w=540n l=14n nf=2
* Cross-Coupled PMOS
XM_P1 OUTP OUTN VDD VDD pmos_rvt w=270n l=14n nf=2
XM_P2 OUTN OUTP VDD VDD pmos_rvt w=270n l=14n nf=2
.ENDS
