import os
import sys
import json
import re
import subprocess
import requests
import shutil
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("❌ ERROR: GEMINI_API_KEY is not set.")
    sys.exit(1)

ALIGN_EXEC = "/home/hussain/ALIGN-public/ALIGN-venv/bin/schematic2layout.py"
PDK_DIR    = "/home/hussain/ALIGN-public/pdks/ALIGN-pdk-sky130/SKY130_PDK"


def extract_spice_instances(spice_text: str) -> set:
    """Extract all transistor instance names from generated SPICE as ALIGN sees them (X_M0, X_M1...)."""
    instances = set()
    for line in spice_text.splitlines():
        line = line.strip()
        if line.lower().startswith("m") and not line.lower().startswith(".model"):
            name = line.split()[0].upper()
            instances.add("X_" + name)
    return instances


def apply_golden_pdk_sizing(spice_text: str) -> str:
    """
    Bypasses ALIGN's brittle pseudo-fin math by forcing all transistors
    to use the exact dimensions from the ALIGN Sky130 golden example.
    """
    spice_text = re.sub(r'\n\s*\+', ' ', spice_text) # Collapse continuation lines
    lines = []
    
    for line in spice_text.splitlines():
        line = line.strip()
        if line.lower().startswith("m") and not line.lower().startswith(".model"):
            parts = line.split()
            
            # 1. Identify if PMOS or NMOS and locate the model index
            is_pmos = False
            model_idx = len(parts)
            for i, p in enumerate(parts):
                p_lower = p.lower()
                if 'pmos' in p_lower or 'pfet' in p_lower:
                    is_pmos = True
                    model_idx = i
                    break
                elif 'nmos' in p_lower or 'nfet' in p_lower:
                    model_idx = i
                    break
            
            # 2. Extract basic nodes (Mname Drain Gate Source Body)
            nodes = parts[:model_idx]
            
            # 3. If the AI forgot the Body terminal, pad it with VDD/VSS
            while len(nodes) < 5:
                nodes.append("VDD" if is_pmos else "VSS")
                
            base_nodes = " ".join(nodes[:5])
            
            # 4. Inject the exact golden string
            if is_pmos:
                line = f"{base_nodes} pmos_rvt w=21e-7 l=150e-9 nf=10 m=1"
            else:
                line = f"{base_nodes} nmos_rvt w=10.5e-7 l=150e-9 nf=10 m=1"
                
        lines.append(line)
        
    return "\n".join(lines)


def sanitize_constraints(constraints: list, valid_instances: set = None) -> list:
    sanitized = []
    for c in constraints:
        if not isinstance(c, dict): continue
        ctype = c.get("constraint", "")

        if ctype == "SymmetricBlocks":
            direction = "V" if str(c.get("direction", "V")).strip().lower() in ("v", "vertical") else "H"
            valid_pairs = []
            for pair in c.get("pairs", []):
                checked = []
                skip = False
                for inst in pair:
                    norm = "X_" + inst.upper().lstrip("X_").lstrip("_")
                    if not norm.startswith("X_M"): norm = "X_" + inst.upper()
                    if valid_instances and norm not in valid_instances:
                        skip = True
                        break
                    checked.append(inst)
                if not skip: valid_pairs.append(checked)

            if valid_pairs:
                sanitized.append({"constraint": "SymmetricBlocks", "pairs": valid_pairs, "direction": direction})
            continue

        if ctype in ("PowerPorts", "GroundPorts"):
            sanitized.append(c)
            
    return sanitized


def build_prompt(design_name: str, raw_spice: str) -> str:
    return f"""You are an expert Analog IC Design Automation engineer using the ALIGN layout tool.

=== STRICT SPICE RULES ===
1. Subcircuit name MUST be: {design_name}
2. Transistors MUST be named mn0, mn1... for NMOS and mp0, mp1... for PMOS.
3. You MUST provide exactly 4 nodes (Drain Gate Source Body) before the model name.
4. Models MUST be: nmos_rvt or pmos_rvt
5. No comments or blank lines inside the .subckt block

=== STRICT JSON CONSTRAINT RULES ===
Use ONLY these constraint types:
1. SymmetricBlocks: {{"constraint": "SymmetricBlocks", "direction": "V", "pairs": [["mn0", "mn1"]]}}
2. PowerPorts: {{"constraint": "PowerPorts", "ports": ["VDD"]}}
3. GroundPorts: {{"constraint": "GroundPorts", "ports": ["VSS"]}}

=== CRITICAL SYMMETRY RULES ===
A SymmetricBlocks pair is ONLY valid when ALL of these are true:
  a) Both transistors are the SAME type (both NMOS OR both PMOS - never mixed)
  b) Both play matching roles (e.g. both are input devices, both are loads)

If the circuit has NO valid symmetric pairs, output: []

=== TASK ===
1. REWRITE the SPICE netlist for {design_name}
2. GENERATE the JSON constraints array - only include SymmetricBlocks if genuinely valid

Format EXACTLY like this:
===SPICE===
[spice code]
===END SPICE===
===JSON===
[json array]
===END JSON===

Raw Netlist:
{raw_spice}"""


def ask_mode() -> int:
    print("\n" + "="*50 + "\n  Select ALIGN Flow Mode\n" + "="*50)
    print("  1 — Floorplanning only  (placement, no routing)")
    print("  2 — Full P&R            (placement + routing)\n" + "="*50)
    while True:
        choice = input("  Enter 1 or 2: ").strip()
        if choice in ("1", "2"): return int(choice)


def process_spice_file(input_file: str, mode: int):
    if not os.path.exists(input_file): sys.exit(1)

    design_name  = os.path.splitext(os.path.basename(input_file))[0].upper()
    project_root = os.path.dirname(os.path.abspath(__file__))
    mode_suffix  = "floorplan" if mode == 1 else "pnr"

    # Versioned workspace — never overwrite previous runs
    version = 1
    while True:
        run_name      = f"workspace_{design_name.lower()}_{mode_suffix}_v{version}"
        workspace_dir = os.path.join(project_root, run_name, design_name.lower())
        if not os.path.exists(os.path.dirname(workspace_dir)):
            break
        version += 1

    os.makedirs(workspace_dir, exist_ok=True)
    print("\n📁 Run folder: " + run_name)

    formatted_spice_path = os.path.join(workspace_dir, f"{design_name.lower()}.sp")
    const_file_path      = os.path.join(workspace_dir, f"{design_name.lower()}.const.json")

    with open(input_file, "r") as f: raw_spice = f.read()

    print(f"\n📖 Reading raw netlist: {input_file}")
    print("🧠 Asking AI to translate SPICE and generate constraints...")

    url     = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"
    payload = {"contents": [{"parts": [{"text": build_prompt(design_name, raw_spice)}]}]}

    try:
        response = requests.post(url, json=payload)
        ai_text = response.json()['candidates'][0]['content']['parts'][0]['text']

        spice_part = ai_text.split("===SPICE===")[1].split("===END SPICE===")[0].strip()
        
        # --- NEW: BYPASS MATH AND APPLY GOLDEN SIZING ---
        spice_part = apply_golden_pdk_sizing(spice_part)

        json_part  = ai_text.split("===JSON===")[1].split("===END JSON===")[0].strip()
        json_part  = re.sub(r'^```[a-z]*\n?', '', json_part).rstrip('`').strip()
        raw_constraints = json.loads(json_part)

        valid_instances = extract_spice_instances(spice_part)
        print("\n🔍 Instances in generated SPICE: " + str(sorted(valid_instances)))

        if len(valid_instances) > 12:
            print(f"\n⚠️  Complex circuit ({len(valid_instances)} instances) — dropping SymmetricBlocks.")
            raw_constraints = [c for c in raw_constraints if c.get("constraint") in ("PowerPorts", "GroundPorts")]

        clean_constraints = sanitize_constraints(raw_constraints, valid_instances)

        with open(formatted_spice_path, "w") as f: f.write(spice_part)
        with open(const_file_path, "w") as f: json.dump(clean_constraints, f, indent=4)
        print(f"\n✅ AI files generated successfully.")

    except Exception as e:
        print(f"❌ AI Phase Failed: {e}"); sys.exit(1)

    align_cmd = [ALIGN_EXEC, workspace_dir, "-p", PDK_DIR, "-s", design_name, "--placer", "python"]
    if mode == 1:
        align_cmd += ["--router_mode", "no_op"]
        mode_label = "Floorplanning only"
    else: mode_label = "Full P&R"

    print("\n🚀 Launching ALIGN engine  [" + mode_label + "]...")
    try:
        subprocess.run(align_cmd, check=True)

        # ── Copy outputs to results/<circuit_name>/ ────────────────────────
        circuit_folder = os.path.join(project_root, "results", design_name.lower())
        os.makedirs(circuit_folder, exist_ok=True)

        if mode == 1:
            # ALIGN always outputs to a fixed 3_pnr/Results relative to project root
            src_dir    = os.path.join(project_root, "3_pnr", "Results")
            extensions = (".json", ".plt", ".pl")
        else:
            src_dir    = project_root
            extensions = (".gds", ".lef", ".python.gds")

        copied = 0
        if os.path.exists(src_dir):
            for fname in os.listdir(src_dir):
                fpath = os.path.join(src_dir, fname)
                if not os.path.isfile(fpath): continue
                if mode == 2 and not fname.upper().startswith(design_name): continue
                if not any(fname.endswith(ext) for ext in extensions): continue
                dst = os.path.join(circuit_folder, fname)
                counter = 2
                while os.path.exists(dst):
                    base, ext = os.path.splitext(fname)
                    dst = os.path.join(circuit_folder, base + "_v" + str(counter) + ext)
                    counter += 1
                shutil.copy2(fpath, dst)
                copied += 1
                print("   📦 " + os.path.basename(dst))

        print("\n🎉 SUCCESS! " + str(copied) + " files saved to results/" + design_name.lower() + "/")
    except subprocess.CalledProcessError as e: print("\n❌ ALIGN failed: " + str(e))


if __name__ == "__main__":
    if len(sys.argv) < 2: sys.exit(1)
    process_spice_file(os.path.abspath(sys.argv[1]), ask_mode())