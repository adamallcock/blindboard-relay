#!/usr/bin/env python3
"""Relay paper figures: knee curves + SVG exemplar grid.

Floors come from the archived deterministic calibration artifact
(calibration-codecv2.json) — never hand-typed. Only relay-v2-stamped
episodes are plotted (same refusal policy as relay_analysis.load_cells).
Numerical note budgets use a logarithmic axis; transcript controls occupy
separate categorical panels. Paired comparisons show their shared seeds."""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_analysis import load_cells, paired_contrast, t_ci

plt.rcParams.update({"font.size": 10, "pdf.fonttype": 42, "svg.fonttype": "path",
                     "svg.hashsalt": "relay-figures-v2"})

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from blindboard.viz import (  # vendored benchkit style constants
    CATEGORICAL as CATEGORICAL_SLOTS,
    GRID,
    SURFACE,
    TEXT,
    TEXT2,
    categorical_map,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper" / "figures"
COLORS = categorical_map(["gpt-5.4-nano", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"])
SHORT = {"gpt-5.4-nano": "nano", "gpt-5.6-luna": "☾ luna",
         "gpt-5.6-terra": "⊕ terra", "gpt-5.6-sol": "☼ sol"}
BUDGETS = ["full", "800", "200", "100", "75", "50", "30", "25"]


def load_sound() -> dict[str, float]:
    cal = json.loads(
        (ROOT / "results/relay/calibration/calibration-codecv2.json").read_text())
    sound = {"full": cal["table"]["r1_reference"]["board_accuracy_mean"]}
    for key, v in cal["table"].items():
        if key.startswith("budget_"):
            sound[key.split("_", 1)[1]] = v["board_accuracy_mean"]
    return sound


def xpos(budget: str) -> float:
    if budget == "retained":
        return math.log2(800) + 2.9
    if budget == "full":
        return math.log2(800) + 1.7
    return math.log2(int(budget))


def load_freeform_cells() -> dict[tuple[str, str], dict[int, float]]:
    cells: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)
    for d in sorted((ROOT / "results/relay/llm").iterdir()):
        sp = d / "summary.json"
        if not sp.exists() or "-long-" in d.name or "-numrow-" in d.name:
            continue
        s = json.loads(sp.read_text())
        if s.get("condition", "freeform") != "freeform":
            continue
        for p in sorted(d.glob("seed*.json")):
            r = json.loads(p.read_text())["result"]
            if r.get("prompt_version") != "relay-v2":
                continue  # refuse unstamped/legacy and nocoach episodes
            cells[(s["model"], str(s["budget"]))][r["seed"]] = r["board_accuracy"]
    return cells


def load_retained_means() -> dict[str, float]:
    """Mean score of each model's retained-reasoning control (std base)."""
    cells: dict[str, dict[int, float]] = defaultdict(dict)
    for d in sorted((ROOT / "results/relay/llm").iterdir()):
        sp = d / "summary.json"
        if not sp.exists() or "-bretained-" not in d.name or "-numrow-" in d.name:
            continue
        s = json.loads(sp.read_text())
        for p in sorted(d.glob("seed*.json")):
            r = json.loads(p.read_text())["result"]
            if r.get("prompt_version") == "relay-v2":
                cells[s["model"]][r["seed"]] = r["board_accuracy"]
    return {m: sum(v.values()) / len(v) for m, v in cells.items() if v}


def style_axis(ax, axis="both"):
    ax.set_facecolor(SURFACE)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(True, axis=axis, color=GRID, linewidth=.6)
    ax.set_axisbelow(True)
    ax.tick_params(colors=TEXT2, labelsize=9)


def point_interval(ax, values, x, color, marker="o"):
    values = list(values)
    mean = sum(values) / len(values)
    lo, hi = t_ci(values)
    ax.errorbar(x, mean, yerr=[[mean-lo], [hi-mean]], color=color,
                marker=marker, markersize=5, linewidth=1.0, capsize=2, zorder=3)
    return mean


def fig_knee():
    """Separate categorical histories from numerical note budgets."""
    cells = load_freeform_cells()
    raw, _ = load_cells("relay-v2")
    cal = json.loads((ROOT / "results/relay/calibration/calibration-codecv2.json").read_text())
    fig = plt.figure(figsize=(6.4, 5.2), facecolor=SURFACE)
    gs = fig.add_gridspec(2, 4, width_ratios=[2.3, .85, 2.3, .85],
                          hspace=.58, wspace=.32)
    shapes = ["o", "^", "s", "D"]
    for index, (model, color) in enumerate(COLORS.items()):
        row, pair = divmod(index, 2)
        ax = fig.add_subplot(gs[row, pair*2]); ctl = fig.add_subplot(gs[row, pair*2+1])
        style_axis(ax); style_axis(ctl, "y")
        budgets = sorted(int(b) for m, b in cells if m == model and b.isdigit())
        pts=[]
        for budget in budgets:
            values = cells[model, str(budget)].values()
            pts.append((budget, point_interval(ax, values, budget, color, shapes[index])))
        ax.plot(*zip(*pts), color=color, linewidth=1.2, zorder=2)
        ref_b = sorted(int(k.split('_')[1]) for k in cal['table'] if k.startswith('budget_'))
        ref_y = [cal['table'][f'budget_{b}']['board_accuracy_mean'] for b in ref_b]
        ax.plot(ref_b, ref_y, '--', color=TEXT2, linewidth=1.0, label='reference (40 seeds)')
        for budget in ref_b:
            values = list(map(float, cal['table'][f'budget_{budget}']['per_seed'].values()))
            mean = sum(values) / len(values); lo, hi = t_ci(values)
            ax.errorbar(budget, mean, yerr=[[mean-lo], [hi-mean]], color=TEXT2,
                        linewidth=.7, capsize=1.5, zorder=1)
        ax.set_xscale('log',base=2);ax.set_xlim(1000,20);ax.set_ylim(0,1.13)
        ax.set_xticks([800,200,100,50,25]);ax.set_xticklabels(['800','200','100','50','25'])
        ax.set_yticks([0,.5,1]);ax.set_xlabel('note budget (code points)',fontsize=9)
        counts=sorted({len(c) for (m,b),c in cells.items() if m==model and b.isdigit()})
        n_label=str(counts[0]) if len(counts)==1 else f'{counts[0]}–{counts[-1]}'
        ax.set_title(f'{SHORT[model]}  ·  n={n_label}',loc='left',fontsize=10.5,color=TEXT)
        if pair==0:ax.set_ylabel('board accuracy',fontsize=10,color=TEXT)
        for j,budget in enumerate(('full','retained')):
            values = [r['board_accuracy'] for r in raw.get((model.rsplit('-',1)[-1], 'freeform','std',budget),{}).values()]
            if values: point_interval(ctl,values,j,color,('s','D')[j])
        ctl.set_ylim(0,1.13);ctl.set_xlim(-.55,1.55);ctl.set_yticks([])
        ctl.set_xticks([0,1]);ctl.set_xticklabels(['visible','retained'],rotation=65,ha='right',fontsize=9)
        ctl.set_title('histories',fontsize=9.5,color=TEXT)
        if index==0:ax.legend(loc='lower left',fontsize=8.5,frameon=False)
    fig.subplots_adjust(left=.10,right=.99,bottom=.13,top=.91)
    fig.suptitle('Free-form notes as the budget tightens',x=.10,ha='left',fontsize=12,color=TEXT)
    return fig


def fig_svg_grid():
    """Full stored canvases, with labelled pixel-exact zooms below."""
    panels = [
        ('results/relay/svg/gpt-5.6-sol-medium-20260714-192940/probe003.png',
         'A  Sol · probe 003', (10,60,260,105)),
        ('results/relay/svg/gpt-5.6-sol-medium-20260714-192940/seed0001_t18.png',
         'B  Sol · seed 1, turn 18', (0,0,240,65)),
        ('results/relay/svg/gpt-5.6-luna-medium-20260714-192939/seed0003_t12.png',
         'C  Luna · seed 3, turn 12', (12,35,245,105)),
        ('results/relay/svg/gpt-5.4-nano-medium-20260714-193339/seed0002_t10.png',
         'D  Nano · seed 2, turn 10', (270,15,512,50)),
    ]
    fig=plt.figure(figsize=(6.4,7.0),facecolor=SURFACE)
    gs=fig.add_gridspec(4,2,height_ratios=[1,.35,1,.35],hspace=.4,wspace=.17)
    for i,(path,label,region) in enumerate(panels):
        row,col=divmod(i,2);image=mpimg.imread(ROOT/path)
        full=fig.add_subplot(gs[2*row,col]);zoom=fig.add_subplot(gs[2*row+1,col])
        full.imshow(image,interpolation='none');full.set_title(label,fontsize=10,color=TEXT,loc='left',pad=5)
        x0,y0,x1,y1=region
        full.add_patch(Rectangle((x0,y0),x1-x0,y1-y0,fill=False,edgecolor=CATEGORICAL_SLOTS[0],linewidth=1))
        zoom.imshow(image[y0:y1,x0:x1],interpolation='none',aspect='equal')
        zoom.set_title('Magnified region · original pixels',fontsize=8.5,color=TEXT2,loc='left',pad=4)
        for ax in (full,zoom):
            ax.set_xticks([]);ax.set_yticks([])
            for spine in ax.spines.values():spine.set_color(GRID)
    fig.subplots_adjust(left=.03,right=.99,bottom=.02,top=.90)
    fig.suptitle('Selected recorded pixel notes',x=.03,ha='left',fontsize=12,color=TEXT)
    return fig

def fig_crossover():
    """Paired B100 scaffold effects; no unordered-category slope chart."""
    raw,_=load_cells('relay-v2')
    analysis=json.loads((ROOT/'results/relay/analysis.json').read_text())
    rows=[r for r in analysis['contrasts'] if r['budget']=='100']
    fig,ax=plt.subplots(figsize=(6.4,5.0),facecolor=SURFACE)
    style_axis(ax,'x');ax.axvline(0,color=TEXT2,linewidth=1,linestyle='--')
    names=[]
    for i,r in enumerate(rows):
        a=raw[r['model'],'freeform','std','100'];b=raw[r['model'],r['condition'],'std','100']
        seeds=sorted(set(a)&set(b)&set(range(10)))
        ds=[b[s]['board_accuracy']-a[s]['board_accuracy'] for s in seeds]
        ax.scatter(ds,[i+((j%5)-2)*.045 for j in range(len(ds))],s=12,color=TEXT2,alpha=.45,zorder=2)
        lo,hi=r['ci'];mean=r['delta']
        ax.errorbar(mean,i,xerr=[[mean-lo],[hi-mean]],color=CATEGORICAL_SLOTS[0],
                    marker='o',capsize=3,linewidth=1.3,zorder=3)
        label={'schema':'schema','form':'form','constitution':'pinned notation'}[r['condition']]
        names.append(f"{r['model']} · {label}")
        ax.text(.84,i,f"{r['p_holm']:.3f}".lstrip('0'),ha='right',va='center',fontsize=10,color=TEXT)
    ax.set_yticks(range(len(rows)));ax.set_yticklabels(names,fontsize=10,color=TEXT)
    ax.invert_yaxis();ax.set_xlim(-.65,.90);ax.set_xticks([-.5,0,.5]);ax.set_xlabel('scaffold − free-form accuracy',fontsize=10)
    ax.text(.98,1.035,'Holm p (24)',transform=ax.transAxes,ha='right',fontsize=9,color=TEXT)
    ax.set_title('Supplied structure: paired effects at B=100',loc='left',fontsize=12,color=TEXT,pad=24)
    fig.tight_layout()
    return fig

# Eight models at B=100, original four then the added four (analysis keys).
MODEL_ROWS = [("nano", "nano"), ("luna", "☾ luna"), ("terra", "⊕ terra"), ("sol", "☼ sol"),
              ("luna6", "☾ GPT-6 Luna"), ("sol6", "☼ GPT-6 Sol"),
              ("flash38", "Gemini 3.8 Flash"), ("opus55", "Opus 5.5")]
# One marker per memory condition; the two transcript controls share a hue.
# A small vertical offset per condition keeps coincident values (models at the
# ceiling) from hiding one another.
REGIMES = [(("freeform", "100"), "free-form notes", "o", CATEGORICAL_SLOTS[2], -0.18),
           (("schema", "100"), "schema notes", "^", CATEGORICAL_SLOTS[0], -0.06),
           (("freeform", "full"), "visible transcript", "s", CATEGORICAL_SLOTS[1], 0.06),
           (("freeform", "retained"), "retained reasoning", "D", CATEGORICAL_SLOTS[3], 0.18)]
ADDED_KEYS = {"luna6", "sol6", "flash38", "opus55"}


def fig_models():
    """Descriptive means beside matched-seed retention contrasts."""
    cells,_=load_cells('relay-v2')
    fig,(ax,contrast)=plt.subplots(1,2,figsize=(6.4,5.0),sharey=True,
                                  gridspec_kw={'width_ratios':[1.65,1.0]},facecolor=SURFACE)
    style_axis(ax,'x');style_axis(contrast,'x')
    labels=[]
    for i,(key,label) in enumerate(MODEL_ROWS):
        labels.append(label)
        for (cond,budget),name,marker,color,dy in REGIMES:
            values=[r['board_accuracy'] for r in cells.get((key,cond,'std',budget),{}).values()]
            if not values:continue
            mean=sum(values)/len(values);lo,hi=t_ci(values)
            ax.errorbar(mean,i+dy,xerr=[[mean-lo],[hi-mean]],color=color,marker=marker,
                        markersize=4,capsize=1.5,linewidth=.8,label=name if i==0 else None,zorder=3)
        a=cells.get((key,'freeform','std','full'),{});b=cells.get((key,'freeform','std','retained'),{})
        # Original rows use all shared seeds: Luna pools F6/F8 descriptively.
        # Added rows use F12 seeds 0--9. Confirmatory families stay separate.
        if key in ADDED_KEYS:a={s:r for s,r in a.items() if s<10};b={s:r for s,r in b.items() if s<10}
        stat=paired_contrast(a,b)
        if stat:
            mean=stat['delta'];lo,hi=stat['ci']
            contrast.errorbar(mean,i,xerr=[[mean-lo],[hi-mean]],color=TEXT,marker='o',capsize=3,linewidth=1.2)
            contrast.text(.66,i,f"n={stat['n']}",ha='right',va='center',fontsize=8.5,color=TEXT2)
    for panel in (ax,contrast):panel.axhline(3.5,color=TEXT2,linewidth=.8,linestyle=':')
    ax.set_yticks(range(len(labels)));ax.set_yticklabels(labels,fontsize=9.5,color=TEXT);ax.invert_yaxis()
    ax.set_xlim(-.04,1.09);ax.set_xticks([0,.5,1]);ax.set_xlabel('board accuracy',fontsize=10)
    contrast.axvline(0,color=TEXT2,linewidth=.8,linestyle='--')
    contrast.set_xlim(-.18,.72);contrast.set_xticks([0,.3,.6]);contrast.set_xlabel('retained − visible',fontsize=10)
    ax.set_title('All-available means',fontsize=10.5,loc='left',color=TEXT)
    contrast.set_title('Paired gain · 95% CI',fontsize=10.5,loc='left',color=TEXT)
    handles,names=ax.get_legend_handles_labels()
    fig.legend(handles,names,loc='upper center',bbox_to_anchor=(.55,.99),ncol=2,fontsize=9,frameon=False)
    fig.subplots_adjust(left=.24,right=.985,bottom=.22,top=.82,wspace=.19)
    fig.text(.24,.055,'Original cohort above divider includes historical controls',fontsize=8.5,color=TEXT2)
    fig.text(.24,.025,'Added cohort below divider: same-day Sep controls',fontsize=8.5,color=TEXT2)
    return fig

FRONTIER_ROWS = [("sol6", "☼ GPT-6 Sol"), ("flash38", "Gemini 3.8 Flash"), ("opus55", "Opus 5.5")]
REFERENCE_GRAY = "#9a9893"


def fig_frontier():
    """Matched initial-seed means and fresh-seed paired comparisons."""
    cells,_=load_cells('relay-v2')
    analysis=json.loads((ROOT/'results/relay/analysis.json').read_text())
    cal=json.loads((ROOT/'results/relay/calibration/calibration-codecv2.json').read_text())
    fig,(ax,fresh)=plt.subplots(1,2,figsize=(6.4,4.1),
                               gridspec_kw={'width_ratios':[1.3,1.0]},facecolor=SURFACE)
    style_axis(ax);style_axis(fresh,'x')
    budgets=['100','50','30'];shapes=['o','^','s']
    reference=[]
    for x,budget in enumerate(budgets):
        per=cal['table'][f'budget_{budget}']['per_seed']
        values=[float(per[str(s)]) for s in range(10)]
        mean=point_interval(ax,values,x,REFERENCE_GRAY,'x');reference.append(mean)
    ax.plot(range(3),reference,'--',color=REFERENCE_GRAY,linewidth=1.0,label='reference (same 10)')
    for i,(key,label) in enumerate(FRONTIER_ROWS):
        color=CATEGORICAL_SLOTS[i]
        for x,budget in enumerate(budgets):
            cell=cells[key,'freeform','std',budget];values=[cell[s]['board_accuracy'] for s in range(10)]
            point_interval(ax,values,x+(i-1)*.13,color,shapes[i])
        ax.plot([],[],marker=shapes[i],color=color,linestyle='none',label=label)
    ax.set_xticks(range(3));ax.set_xticklabels(budgets);ax.set_ylim(0,1.13);ax.set_xlim(-.4,2.4)
    ax.set_ylabel('board accuracy',fontsize=10);ax.set_xlabel('note budget · categorical spacing',fontsize=9)
    ax.set_title('Initial seeds 0–9',loc='left',fontsize=10.5,color=TEXT)
    rows=analysis['families']['F16_frontier_separation_fresh']
    for i,r in enumerate(rows):
        mean=r['delta'];lo,hi=r['ci']
        fresh.errorbar(mean,i,xerr=[[mean-lo],[hi-mean]],color=TEXT,marker='o',capsize=3,linewidth=1.2)
        fresh.text(.02,i+.27,f"{r['n_pos']} wins / {r['n_neg']} losses / {r['n']-r['n_pos']-r['n_neg']} ties",
                   fontsize=8.5,color=TEXT2,transform=fresh.get_yaxis_transform())
    short=['Flash − Sol','Opus − Sol','Opus − Flash']
    fresh.set_yticks(range(len(rows)));fresh.set_yticklabels(short,fontsize=9,color=TEXT)
    fresh.invert_yaxis();fresh.set_ylim(2.65,-.6);fresh.axvline(0,color=TEXT2,linestyle='--',linewidth=.8)
    fresh.set_xlim(-.25,.33);fresh.set_xticks([-.2,0,.2]);fresh.set_xlabel('paired accuracy difference',fontsize=9)
    fresh.set_title('Fresh seeds 10–29 · B=50',loc='left',fontsize=10.5,color=TEXT)
    handles,names=ax.get_legend_handles_labels()
    fig.legend(handles,names,loc='upper center',bbox_to_anchor=(.5,1.01),ncol=2,frameon=False,fontsize=9)
    fig.subplots_adjust(left=.09,right=.99,bottom=.18,top=.78,wspace=.53)
    return fig

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fig in [("relay_fig1_knee", fig_knee()), ("relay_fig2_svg_notes", fig_svg_grid()),
                      ("relay_fig3_crossover", fig_crossover()), ("relay_fig4_models", fig_models()),
                      ("relay_fig5_frontier", fig_frontier())]:
        for ext in ("svg", "pdf", "png"):
            fig.savefig(OUT / f"{name}.{ext}", dpi=170, facecolor=SURFACE, bbox_inches="tight")
        svg = OUT / f"{name}.svg"
        svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
        plt.close(fig)
        print(f"wrote paper/figures/{name}.{{svg,pdf,png}}")


if __name__ == "__main__":
    main()
