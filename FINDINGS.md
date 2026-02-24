# Findings — Floorplanning AI Accelerator

## Overview

This document summarizes the key findings from testing an AI-driven analog layout constraint generation pipeline across four circuit topologies. The pipeline uses Gemini 2.5 Flash to translate raw SPICE netlists into ALIGN-compatible constraints, then validates the output with a second Gemini pass before rendering a floorplan visualization.

---

## Finding 1: LLMs Correctly Identify Symmetric Pairs in Analog Circuits

**Circuits tested:** Comparator (9T), Five-Transistor OTA (5T), Differential Amplifier (5T)

For all three analog circuits, Gemini correctly identified which transistor pairs require symmetric placement purely from netlist connectivity — without any explicit topology hints. The comparator produced 4 valid symmetric pairs covering the cross-coupled regeneration pair, the differential input pair, and the load pair. The OTA and diff amp each produced the expected NMOS differential pair match.

**Conclusion:** LLMs have sufficient analog circuit knowledge to perform constraint generation from a raw netlist. The semantic understanding of circuit function (differential pair, current mirror, cross-coupled latch) is present in the model and transfers correctly to layout constraints.

---

## Finding 2: LLMs Hallucinate Constraints for Digital/Simple Circuits

**Circuit tested:** Buffer (4T), Inverter (2T)

For a two-inverter buffer chain, Gemini generated SymmetricBlocks pairs grouping PMOS with NMOS transistors — a physically invalid constraint since symmetric pairs require matching device types. An inverter is a series stack of one PMOS and one NMOS; there is no symmetric relationship between them.

This is a classic LLM failure mode: **pattern over-generalization**. The model learned the differential pair symmetry pattern from analog circuits and applied it incorrectly to digital topologies where it does not belong.

The validation layer caught this automatically — both invalid pairs were flagged with red borders and warning messages in the visualizer, explaining that the devices were different types.

**Conclusion:** A validation stage is essential. The same LLM, given richer context (full connectivity + explicit validation task), correctly identified and explained its own earlier mistake. This demonstrates that LLM-assisted EDA flows require a structured human-in-the-loop review step, but also that the review can be AI-assisted.

---

## Finding 3: Complex Circuits Exceed ALIGN's Constraint Scope

**Circuit tested:** Cascode Current Mirror OTA (20T)

For circuits with more than 12 transistors, ALIGN's compiler groups related devices into internal array hierarchies before place-and-route begins. Once grouped, top-level instance names (e.g. X_M13) no longer exist at the hierarchy level where constraints are applied — causing a pydantic ValidationError crash.

The pipeline detects this automatically: circuits with more than 12 instances have their SymmetricBlocks constraints dropped before ALIGN runs, keeping only PowerPorts and GroundPorts. This prevents crashes but means complex circuits lose their analog placement guidance.

**Conclusion:** Constraint generation complexity scales non-linearly with circuit size. A production-grade tool would need to inspect ALIGN's internal hierarchy and remap constraints to the correct hierarchical level. This is a known limitation of the current approach and a direction for future work.

---

## Finding 4: Mock PDK Does Not Enforce Physical Design Rules

**Observed during:** All circuit runs on FinFET14nm Mock PDK

The Mock PDK treats all transistors as abstract rectangles with no diffusion awareness. As a result, PMOS and NMOS blocks can be placed in the same row without any design rule violation — which would be physically impossible in real silicon where PMOS must reside in an n-well isolated from the p-substrate.

When tested on the Sky130 PDK, ALIGN enforces proper layer separation and generates GDS output with real metal layers, contacts, and diffusion regions. The GDS layout looks significantly different from the abstract floorplan — dense, multi-layer, and DRC-aware.

**Conclusion:** The Mock PDK is sufficient for validating the constraint generation and placement logic, but Sky130 is required to validate physical correctness. Both PDKs were used in this project, with Sky130 used for final GDS output.

---

## Finding 5: The Human Role Shifts from Authoring to Reviewing

The most significant practical finding is about workflow, not accuracy. Writing analog layout constraints manually requires deep knowledge of both the circuit topology and the EDA tool's constraint schema. A layout engineer might spend 30–60 minutes writing and debugging constraints for a 9-transistor comparator.

With this pipeline, Gemini generates a first draft in under 10 seconds. Even when the draft contains errors (as in the buffer case), catching and correcting an error is faster than writing all constraints from scratch. The visualizer makes errors immediately obvious — no need to run ALIGN and debug a cryptic crash.

**Conclusion:** AI-assisted constraint generation is a genuine productivity improvement even when the output is imperfect. The engineer's role shifts from constraint authorship to constraint review — a meaningful reduction in cognitive load for a task that currently requires significant manual effort.

---

## Test Results Summary

| Circuit | Transistors | Valid Constraints | Sym Pairs | Notes |
|---|:---:|:---:|:---:|---|
| Inverter | 2 | ✗ (caught) | 0 | Hallucinated PMOS+NMOS pair — flagged |
| Buffer | 4 | ✗ (caught) | 0 | Same hallucination — both pairs flagged |
| Diff Amp | 5 | ✓ | 2 | PMOS mirror + NMOS diff pair correct |
| Five-Transistor OTA | 5 | ✓ | 1 | NMOS diff pair correct, tail unpaired |
| Comparator | 9 | ✓ | 4 | All pairs correctly identified |
| Cascode OTA | 20 | N/A | 0 | Too complex — hierarchy conflict |

---

## Limitations

- Sky130 PDK crashes on the comparator (9T) due to placer limitations — comparator tested on Mock PDK only
- Tail current source sized identically to diff pair due to golden sizing override — visual sizing difference lost
- No timing or power analysis — placement quality is evaluated structurally, not electrically
- Single LLM temperature setting — constraint quality varies between runs for the same netlist
