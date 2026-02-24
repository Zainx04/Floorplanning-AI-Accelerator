"""
visualize.py  —  Floorplanning AI Accelerator
Reads ALIGN placement JSON + optional .pl file, calls Gemini to
validate constraints and annotate the floorplan, then renders a
clean matplotlib figure.

Usage:
    python3 visualize.py <*_scaled_placement_verilog.json> [output.png]
"""

import json, sys, os, glob, re
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import matplotlib.patheffects as pe
import numpy as np
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

# ── Palette ───────────────────────────────────────────────────────────────────
BG       = "#0f1117"
DIE_BG   = "#161b22"
DIE_EDGE = "#30363d"
PANEL_BG = "#1a1f26"
KINDS = {
    "NMOS": dict(face="#0d2137", edge="#4493f8"),
    "PMOS": dict(face="#2a0d1f", edge="#e879a0"),
    "DP":   dict(face="#0d2419", edge="#2ea043"),
}
SYM_COL  = ["#f0b429","#79c0ff","#ff7b72","#a5d6a7","#d2a8ff"]
PORT_C   = "#ffa657"
TEXT_C   = "#e6edf3"
MUTED_C  = "#656d76"
ACCENT_C = "#f0b429"
WARN_C   = "#f85149"
OK_C     = "#2ea043"


# ── Helpers ───────────────────────────────────────────────────────────────────
def kind(ab):
    u = ab.upper()
    if "DP_" in u:  return "DP"
    if "PMOS" in u: return "PMOS"
    return "NMOS"

def leaf_size(leaves, ab):
    for l in leaves:
        if l["abstract_name"] == ab:
            b = l["bbox"]; return b[2]-b[0], b[3]-b[1]
    return 640, 2352

def place(tw, th, tx):
    ox,oy,sx,sy = tx["oX"],tx["oY"],tx["sX"],tx["sY"]
    return (ox if sx==1 else ox-tw), (oy if sy==1 else oy-th), tw, th


# ── Gemini analysis ───────────────────────────────────────────────────────────
def gemini_analyze(design: str, instances: list, pairs: list, ports: list) -> dict:
    """
    Ask Gemini to:
    1. Validate whether the symmetric pairs make analog circuit sense
    2. Identify the role of each instance (e.g. input diff pair, load, tail)
    3. Write a 2-sentence plain-English summary of the floorplan
    Returns dict with keys: roles, pair_valid, warnings, summary
    """
    if not API_KEY:
        return {"roles": {}, "pair_valid": {}, "warnings": ["No GEMINI_API_KEY set — skipping AI analysis"], "summary": ""}

    inst_summary = "\n".join(
        f"  {i['instance_name']} ({i['abstract_template_name']}) "
        f"connects to: {', '.join(m['actual'] for m in i['fa_map'])}"
        for i in instances
    )
    
    pair_summary = "\n".join(f"  {' ↔ '.join(str(item) for item in p)}" for p in pairs)
    port_list    = ", ".join(ports)

    prompt = f"""You are an analog IC layout expert analyzing an ALIGN floorplan output.

Design: {design}
Ports: {port_list}

Instances:
{inst_summary}

Proposed symmetric pairs:
{pair_summary if pairs else "  None"}

Answer in this EXACT JSON format (no markdown, no explanation outside the JSON):
{{
  "roles": {{
    "X_M0": "short role description (e.g. NMOS input transistor)",
    "X_M1": "..."
  }},
  "pair_valid": {{
    "X_M0,X_M1": true,
    "X_M2,X_M3": false
  }},
  "warnings": [
    "warning message if a pair is wrong or suspicious"
  ],
  "summary": "2-sentence plain English summary of what this circuit is and how the floorplan is arranged."
}}

Rules:
- A symmetric pair is VALID only if both devices have the same type (both NMOS or both PMOS) AND play matching roles in the circuit (e.g. differential pair, load pair, cross-coupled pair).
- A pair is INVALID if the devices have different types or clearly unrelated circuit roles.
- Keep role descriptions under 6 words.
- Keep summary under 40 words.
"""

    url     = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        raw = re.sub(r'^```[a-z]*\n?', '', raw).rstrip('`').strip()
        return json.loads(raw)
    except Exception as e:
        return {
            "roles": {},
            "pair_valid": {},
            "warnings": [f"AI analysis failed: {e}"],
            "summary": ""
        }


# ── Main draw ─────────────────────────────────────────────────────────────────
def draw(json_path: str, out_path: str):
    with open(json_path) as f: data = json.load(f)
    mod    = data["modules"][0]
    leaves = data["leaves"]
    design = mod["abstract_name"]
    dw, dh = mod["bbox"][2], mod["bbox"][3]

    # Symmetric pairs from constraints
    pairs = []
    for c in mod.get("constraints", []):
        if c.get("constraint") == "SymmetricBlocks":
            for p in c.get("pairs", []): 
                # THE ROOT FIX: Only keep perfect length-2 pairs!
                if len(p) == 2:
                    pairs.append(tuple(p))

    # Ports from .pl file
    ports = {}
    for pf in glob.glob(os.path.join(os.path.dirname(json_path), "*.pl")):
        with open(pf) as f:
            for line in f:
                pts = line.strip().split()
                if len(pts)==3 and not pts[0].startswith("X_") and pts[0]!="DIE":
                    try: ports[pts[0]] = (float(pts[1]), float(pts[2]))
                    except: pass

    # ── Gemini analysis ───────────────────────────────────────────────────────
    print("🤖 Asking Gemini to analyze the floorplan...")
    analysis  = gemini_analyze(design, mod["instances"], pairs, list(ports.keys()))
    roles     = analysis.get("roles", {})
    pv        = analysis.get("pair_valid", {})
    warnings  = analysis.get("warnings", [])
    summary   = analysis.get("summary", "")

    # Build pair validity lookup  key = "A,B"
    def is_valid(a, b):
        key1, key2 = f"{a},{b}", f"{b},{a}"
        if key1 in pv: return pv[key1]
        if key2 in pv: return pv[key2]
        return True   # default: trust it

    # Pair color map  (red if invalid)
    pcol = {}
    for i, (a, b) in enumerate(pairs):
        col = SYM_COL[i % len(SYM_COL)] if is_valid(a, b) else WARN_C
        pcol[a] = col
        pcol[b] = col

    # ── Figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(14, 9), facecolor=BG)
    ax  = fig.add_axes([0.03, 0.08, 0.56, 0.83])
    axp = fig.add_axes([0.63, 0.08, 0.35, 0.83])

    ax.set_facecolor(DIE_BG)
    axp.set_facecolor(PANEL_BG)
    axp.set_xlim(0,1); axp.set_ylim(0,1); axp.axis("off")
    axp.add_patch(mpatches.FancyBboxPatch((0,0),1,1,
        boxstyle="round,pad=0.01", lw=1.2,
        edgecolor=DIE_EDGE, facecolor="none",
        transform=axp.transAxes, clip_on=False))

    PAD = dw * 0.08
    ax.set_xlim(-PAD, dw+PAD)
    ax.set_ylim(-PAD*0.5, dh+PAD*0.7)
    ax.set_aspect("equal")

    for gx in np.linspace(0, dw, 7):
        ax.axvline(gx, color="#1c2128", lw=0.5, zorder=0)
    for gy in np.linspace(0, dh, 9):
        ax.axhline(gy, color="#1c2128", lw=0.5, zorder=0)

    ax.add_patch(mpatches.FancyBboxPatch((0,0), dw, dh,
        boxstyle="round,pad=0", lw=2,
        edgecolor=DIE_EDGE, facecolor="none", zorder=1))

    types_seen = set()
    for inst in mod["instances"]:
        nm  = inst["instance_name"]
        ab  = inst["abstract_template_name"]
        tx  = inst["transformation"]
        k   = kind(ab)
        tw, th = leaf_size(leaves, ab)
        x,y,w,h = place(tw, th, tx)
        fc  = KINDS[k]["face"]
        ec  = pcol.get(nm, KINDS[k]["edge"])
        lw  = 2.8 if nm in pcol else 1.5
        
        # Safely determine validity for the hatch overlay
        valid = is_valid(*next(((a,b) for a,b in pairs if nm in (a,b)), (nm,nm)))

        ax.add_patch(FancyBboxPatch(
            (x+50,y+50), w-100, h-100,
            boxstyle="round,pad=40",
            lw=lw, edgecolor=ec, facecolor=fc, alpha=0.96, zorder=2))

        # Invalid pair — red hatch overlay
        if nm in pcol and not valid:
            ax.add_patch(FancyBboxPatch(
                (x+50,y+50), w-100, h-100,
                boxstyle="round,pad=40",
                lw=0, facecolor="none",
                hatch="///", edgecolor=WARN_C,
                alpha=0.25, zorder=3))

        short = nm.replace("X_","")
        cx,cy = x+w/2, y+h/2

        ax.text(cx, cy+h*0.1, short,
            ha="center", va="center", fontsize=8.5, fontweight="bold",
            color=TEXT_C, zorder=4,
            path_effects=[pe.withStroke(linewidth=2.5, foreground=BG)])

        # Role from Gemini (small italic text)
        role = roles.get(nm, "")
        if role:
            ax.text(cx, cy-h*0.12, role,
                ha="center", va="center", fontsize=5,
                color=ec, alpha=0.8, style="italic", zorder=4,
                path_effects=[pe.withStroke(linewidth=1.5, foreground=BG)])
        else:
            ax.text(cx, cy-h*0.2,
                {"NMOS":"NMOS","PMOS":"PMOS","DP":"DP-NMOS"}[k],
                ha="center", va="center", fontsize=5.5,
                color=ec, alpha=0.7, zorder=4,
                path_effects=[pe.withStroke(linewidth=1.5, foreground=BG)])

        types_seen.add(k)

    # Sym axis lines
    for i,(a,b) in enumerate(pairs):
        xs = []
        for inst in mod["instances"]:
            if inst["instance_name"] in (a,b):
                ab2=inst["abstract_template_name"]
                tw2,th2=leaf_size(leaves,ab2)
                rx,ry,rw,rh=place(tw2,th2,inst["transformation"])
                xs.append(rx+rw/2)
        if xs:
            mid = sum(xs)/len(xs)
            valid = is_valid(a,b)
            col = SYM_COL[i%len(SYM_COL)] if valid else WARN_C
            ax.axvline(mid, color=col, lw=1.1,
                linestyle=(0,(5,4)), alpha=0.5, zorder=1)
            ax.text(mid, dh+PAD*0.35, f"SYM {i+1}",
                ha="center", va="bottom", fontsize=6, color=col, alpha=0.85)

    # Ports
    for pname,(px,py) in ports.items():
        px_c = max(0, min(dw, px))
        py_c = max(0, min(dh, py))
        ax.plot(px_c, py_c, "o", color=PORT_C, markersize=7, zorder=5,
            markeredgecolor=BG, markeredgewidth=1.2)
        ha = "right" if px_c < dw*0.3 else ("left" if px_c > dw*0.7 else "center")
        ox_ = -dw*0.04 if ha=="right" else (dw*0.04 if ha=="left" else "center")
        if ox_ == "center":
            ox_ = 0
        ax.text(px_c+ox_, py_c, pname,
            ha=ha, va="center", fontsize=7, color=PORT_C,
            fontweight="bold", zorder=5,
            path_effects=[pe.withStroke(linewidth=2, foreground=BG)])

    ax.tick_params(colors=MUTED_C, labelsize=6.5)
    for sp in ax.spines.values(): sp.set_edgecolor(DIE_EDGE)
    ax.set_xlabel("X  (ALIGN units)", color=MUTED_C, fontsize=7.5, labelpad=5)
    ax.set_ylabel("Y  (ALIGN units)", color=MUTED_C, fontsize=7.5, labelpad=5)

    # ── Info panel ────────────────────────────────────────────────────────────
    def ptxt(txt, y, x=0.06, size=8.5, color=TEXT_C, bold=False, alpha=1.0, italic=False):
        axp.text(x, y, txt, transform=axp.transAxes,
            fontsize=size, color=color, va="top", alpha=alpha,
            fontweight="bold" if bold else "normal",
            style="italic" if italic else "normal",
            wrap=True)

    def divider(y):
        axp.plot([0.04,0.96],[y,y], color=DIE_EDGE,
            lw=0.8, transform=axp.transAxes)

    y = 0.96
    ptxt("DESIGN INFO", y, size=6.5, color=ACCENT_C, bold=True); y-=0.05
    ptxt(design, y, size=12, bold=True); y-=0.065
    ptxt(f"Die   {dw} × {dh} units",     y, size=7.5, color=MUTED_C); y-=0.04
    ptxt(f"Instances   {len(mod['instances'])}", y, size=7.5, color=MUTED_C); y-=0.04
    ptxt(f"Sym pairs   {len(pairs)}",     y, size=7.5, color=MUTED_C); y-=0.04
    ptxt(f"Ports   {len(ports)}",          y, size=7.5, color=MUTED_C); y-=0.045

    # AI Summary
    if summary:
        divider(y); y-=0.04
        ptxt("AI SUMMARY", y, size=6.5, color=ACCENT_C, bold=True); y-=0.045
        # Word-wrap manually at ~42 chars
        words = summary.split()
        line, lines = "", []
        for w in words:
            if len(line)+len(w)+1 > 42:
                lines.append(line.strip()); line = w+" "
            else:
                line += w+" "
        if line: lines.append(line.strip())
        for ln in lines:
            ptxt(ln, y, size=7.2, color=TEXT_C, alpha=0.85, italic=True); y-=0.038

    divider(y); y-=0.04
    ptxt("CELL TYPES", y, size=6.5, color=ACCENT_C, bold=True); y-=0.048
    for k_,label in [("NMOS","NMOS"),("PMOS","PMOS"),("DP","Diff-Pair NMOS")]:
        if k_ not in types_seen: continue
        axp.add_patch(mpatches.FancyBboxPatch(
            (0.06, y-0.028), 0.09, 0.024,
            boxstyle="round,pad=0.003",
            transform=axp.transAxes, clip_on=False,
            lw=1.2, edgecolor=KINDS[k_]["edge"],
            facecolor=KINDS[k_]["face"]))
        ptxt(label, y-0.016, x=0.20, size=7.5); y-=0.05

    divider(y); y-=0.04
    ptxt("SYMMETRIC PAIRS", y, size=6.5, color=ACCENT_C, bold=True); y-=0.048
    for i,(a,b) in enumerate(pairs):
        valid = is_valid(a,b)
        col   = SYM_COL[i%len(SYM_COL)] if valid else WARN_C
        label = f"{a.replace('X_','')}  ↔  {b.replace('X_','')}"
        badge = "  ✓" if valid else "  ✗ invalid"
        axp.plot([0.06,0.15],[y-0.016,y-0.016], color=col, lw=2,
            linestyle=(0,(4,2)), transform=axp.transAxes)
        ptxt(label+badge, y-0.008, x=0.19, size=7,
            color=col if valid else WARN_C); y-=0.046

    # Warnings
    if warnings:
        divider(y); y-=0.04
        ptxt("⚠ WARNINGS", y, size=6.5, color=WARN_C, bold=True); y-=0.045
        for w in warnings:
            # wrap at 40 chars
            words2 = w.split()
            ln2, lns2 = "", []
            for wd in words2:
                if len(ln2)+len(wd)+1>40: lns2.append(ln2.strip()); ln2=wd+" "
                else: ln2+=wd+" "
            if ln2: lns2.append(ln2.strip())
            for ln in lns2:
                ptxt(ln, y, size=6.5, color=WARN_C, alpha=0.9); y-=0.035

    divider(y); y-=0.04
    ptxt("FLOW STATUS", y, size=6.5, color=ACCENT_C, bold=True); y-=0.046
    for step,done in [("Topology","✓"),("Primitives","✓"),
                       ("Placement","✓"),("Routing","✗")]:
        col = OK_C if done=="✓" else WARN_C
        ptxt(f"{done}   {step}", y, size=8, color=col); y-=0.044

    # ── Title ─────────────────────────────────────────────────────────────────
    fig.text(0.03, 0.935, "Floorplanning AI Accelerator",
        fontsize=8.5, color=MUTED_C, va="bottom")
    fig.text(0.03, 0.955, f"AI-Generated Floorplan  —  {design}",
        fontsize=13, fontweight="bold", color=TEXT_C, va="bottom")

    plt.savefig(out_path, dpi=180, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"✅ Saved → {out_path}")

    # ── Copy PNG to results/<circuit_name>/ ──────────────────────────────
    import shutil
    # Walk up from the JSON path to find the project root (has main.py)
    search = os.path.abspath(json_path)
    project_root = None
    for _ in range(8):
        search = os.path.dirname(search)
        if os.path.exists(os.path.join(search, "main.py")):
            project_root = search
            break
    if project_root is None:
        project_root = os.path.dirname(os.path.abspath(__file__))

    circuit_name = design.lower()
    results_dir  = os.path.join(project_root, "results", circuit_name)
    os.makedirs(results_dir, exist_ok=True)

    fname   = os.path.basename(out_path)
    dst     = os.path.join(results_dir, fname)
    counter = 2
    while os.path.exists(dst):
        base, ext = os.path.splitext(fname)
        dst = os.path.join(results_dir, base + "_v" + str(counter) + ext)
        counter += 1
    shutil.copy2(out_path, dst)
    print("   📦 Copied to: results/" + circuit_name + "/" + os.path.basename(dst))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 visualize.py <*_scaled_placement_verilog.json> [out.png]")
        sys.exit(1)
    inp  = sys.argv[1]
    if len(sys.argv) > 2:
        outp = sys.argv[2]
    else:
        # Auto-name: never overwrite — append _v2, _v3 if file exists
        base = inp.replace(".json", "_floorplan.png")
        outp = base
        counter = 2
        while os.path.exists(outp):
            outp = base.replace("_floorplan.png", f"_floorplan_v{counter}.png")
            counter += 1
    draw(inp, outp)