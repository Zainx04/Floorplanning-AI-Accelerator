# Floorplanning AI Accelerator

An AI-powered pipeline that takes a raw SPICE netlist, uses Gemini to generate analog layout constraints, runs the ALIGN open-source place-and-route engine, and visualizes the floorplan with a second AI validation pass.

Built as part of a Graduate Project in Analog IC Design Automation.

---

## What It Does

```
Raw SPICE netlist
      │
      ▼
Gemini 2.5 Flash
  • Rewrites SPICE to ALIGN format
  • Identifies symmetric device pairs
  • Generates placement constraints
      │
      ▼
ALIGN Place & Route Engine (Sky130 PDK)
  • Topology identification
  • Primitive generation
  • Floorplan placement
  • Optional full routing
      │
      ▼
Gemini Validation + Visualizer
  • Validates each symmetric pair
  • Flags invalid constraints with warnings
  • Renders annotated floorplan PNG
  • Copies all outputs to results/
```

---

## Results

### Comparator (9 transistors)
4 symmetric pairs correctly identified — cross-coupled pair, differential input pair, load pair, regeneration pair.

### Five-Transistor OTA (5 transistors)
PMOS current mirror load on top, NMOS differential pair in middle, tail current source at bottom. 1 correct symmetric pair.

### Differential Amplifier (5 transistors)
Clean placement with 2 correct symmetric pairs — PMOS mirror load and NMOS input pair.

All results are in the `results/` folder.

---

## Project Structure

```
Floorplanning-AI-Accelerator/
├── main.py                  ← Main pipeline (AI + ALIGN)
├── visualize.py             ← Floorplan renderer + AI validator
├── input_circuits/          ← Raw SPICE netlists
│   ├── comparator.sp
│   ├── five_transistor_ota.sp
│   ├── diff_amp.sp
│   └── buffer.sp
├── results/                 ← All outputs organized by circuit
│   ├── comparator/
│   ├── five_transistor_ota/
│   └── diff_amp/
├── .env.example             ← API key template
└── requirements.txt
```

---

## Setup

**Requirements:**
- Python 3.8+
- ALIGN installed (`schematic2layout.py` on PATH)
- Sky130 PDK (`ALIGN-pdk-sky130`)
- Gemini API key

```bash
# 1. Clone
git clone https://github.com/Zainx04/Floorplanning-AI-Accelerator
cd Floorplanning-AI-Accelerator

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set API key
cp .env.example .env
# Edit .env and add: GEMINI_API_KEY=your_key_here
```

---

## Usage

```bash
# Run the pipeline
python3 main.py input_circuits/comparator.sp

# Choose mode:
#   1 — Floorplanning only (fast, no routing)
#   2 — Full P&R (placement + routing + GDS output)

# Visualize the result
python3 visualize.py results/comparator/COMPARATOR_0_scaled_placement_verilog.json
```

Outputs are automatically saved to `results/<circuit_name>/` — versioned, never overwritten.

---

## Key Findings

See `FINDINGS.md` for the full analysis.

**Short version:**
- LLMs correctly identify symmetric device pairs in analog circuits from netlist connectivity alone
- LLMs hallucinate constraints for digital circuits (inverters, buffers) — the validation layer catches these
- Complex circuits (>12 transistors) cause ALIGN array hierarchy conflicts with top-level constraints
- The Mock PDK does not enforce n-well separation between PMOS and NMOS — Sky130 does
- Human review of AI-generated constraints is faster than writing them from scratch

---

## Tech Stack

| Component | Tool |
|---|---|
| Constraint generation | Gemini 2.5 Flash |
| Constraint validation | Gemini 2.5 Flash |
| Place & Route | ALIGN (open source) |
| PDK | Sky130 (FinFET14nm Mock for comparison) |
| Visualization | Matplotlib |
| Language | Python 3.8 |
