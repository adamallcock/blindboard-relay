#!/usr/bin/env python3
"""Relay explainer figures for the introduction (paper Figure 1).

relay_figA_loop: three consecutive turns of one stored relay episode
(gpt-5.6-luna, free-form notes, B=100, seed 0, turns 4-6). Per turn: what
the fresh instance sees (rules, the observation, its predecessor's note),
its reasoning (discarded when the turn ends), and what it writes (four
presses and a new note, cut at B characters). Under each note, the 26-key
board in the walkthrough's visual language: green = what the note states,
blue outline = keys pressed this turn, orange = keys this turn's rotation
notice names, small gray = the hidden layout at the start of the turn,
which the model never sees.

Nothing in panel (a) is typed by hand. Notes, observations, presses and
rotations are read from the stored episode; the hidden layout is rebuilt by
replaying the episode through the environment and checked against every
stored record; the pins drawn on each board are parsed from the note text
and checked against that layout.

relay_figA_regimes: what reaches a turn under the relay note and under the
two transcript controls, with nano's mean score at B=100 in each. Scores and
paired gaps come from relay_analysis.load_cells, the loader behind the
generated ladder table, so the figure cannot drift from the tables.

Colors: the walkthrough's (imported from make_walkthrough_figures.py) and
the vendored benchkit palette (blindboard/viz.py).

  uv run --with matplotlib python scripts/make_relay_explainer.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Ellipse, FancyArrowPatch, FancyBboxPatch, Polygon
from matplotlib.path import Path as MPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from make_walkthrough_figures import DEDUCE, KEYFACE, PRESS, ROTATE

from blindboard.env import Action, Episode
from blindboard.protocol import extract_json
from blindboard.viz import SURFACE, TEXT, TEXT2
from relay.tiers import BASES

OUT = ROOT / "paper" / "figures"
EPISODE = ROOT / "results/relay/llm/gpt-5.6-luna-medium-freeform-b100-20260714-180239/seed0000.json"
FIRST_TURN = 4  # panels show FIRST_TURN .. FIRST_TURN + 2
LOST = "#b3261e"  # torn-off text and discarded reasoning
PAPER = "#ffffff"  # the note card
PANEL = "#f4f3ef"  # the sees / writes boxes
EDGE = "#d8d7d3"  # key and box outlines (walkthrough key edge)
MUTED = "#b9b7b0"  # the walkthrough's "?" gray
TRUTH = "#a8a69f"  # hidden-truth letters, slightly darker than the walkthrough's for print

plt.rcParams.update({"font.family": "DejaVu Sans", "pdf.fonttype": 42, "svg.fonttype": "path",
                     "svg.hashsalt": "relay-explainer"})
MONO = "DejaVu Sans Mono"
MONO_ADVANCE = 0.6021  # DejaVu Sans Mono advance width, in em
# Both figures are drawn at the paper's \linewidth (6.4 in) and included at
# 100%, so every font size below is the printed size in points.
W = 6.4
FS = 8.0  # body type at the paper's full text width
CARD_FS = 8.2  # verbatim notes must be readable at normal PDF size
CARD_ROW = 25  # characters per note-card row

FINGER_ABBR = {"pinky": "p", "ring": "r", "middle": "m", "index": "i"}
FINGER_FULL = {v: k for k, v in FINGER_ABBR.items()}
ROW_ABBR = {"top": "T", "home": "H", "bottom": "B"}
ROW_FULL = {"t": "top", "h": "home", "b": "bottom"}
ROWS3 = ("top", "home", "bottom")


# ----------------------------------------------------------------- the data

def abbr(address: str) -> str:
    """L-index-bottom-in -> LiBi: the abbreviation the model itself uses
    (hand, finger initial, row initial, trailing i for the inner reach)."""
    hand, finger, row, *reach = address.split("-")
    return hand + FINGER_ABBR[finger] + ROW_ABBR[row] + ("i" if reach else "")


_ADDR = r"([LR])([prmi])([TtHhBb])(i?)"
_ADDR_NC = r"[LR][prmi][TtHhBb]i?"
# "LrH=L" is a pin; "LpB=M before rotation" is the note flagging a stale pin.
_PIN = re.compile(rf"(?<![A-Za-z]){_ADDR}\s*=\s*([A-Z])(?![A-Za-z])(?!\s+before)")
_SET = re.compile(rf"(?<![A-Za-z])((?:{_ADDR_NC}[/,])+{_ADDR_NC})\s*=\s*\{{([A-Z](?:,[A-Z])*)\}}")


def _expand(hand: str, finger: str, row: str, inner: str) -> str:
    return f"{hand}-{FINGER_FULL[finger]}-{ROW_FULL[row.lower()]}" + ("-in" if inner else "")


def parse_note(note: str, board) -> tuple[dict[int, str], dict[int, str]]:
    """Pins {pos: symbol} and set facts {pos: 'Y/Z'} stated in a note."""
    pins: dict[int, str] = {}
    for m in _PIN.finditer(note):
        pins[board.index_of(_expand(*m.groups()[:4]))] = m.group(5)
    sets: dict[int, str] = {}
    for m in _SET.finditer(note):
        keys = re.findall(_ADDR, m.group(1))
        syms = "/".join(m.group(2).split(","))
        for k in keys:
            pos = board.index_of(_expand(*k))
            if pos not in pins:
                sets[pos] = syms
    return pins, sets


def load_episode() -> dict:
    """The panel data for turns FIRST_TURN..FIRST_TURN+2, every field read
    from the stored episode and cross-checked by replay."""
    data = json.loads(EPISODE.read_text())
    result = data["result"]
    config = BASES["std"]
    if config.to_dict() != result["config"]:
        raise SystemExit(f"{EPISODE.name}: stored config is not the relay std base")
    budget = int(result["budget_chars"])

    # Replay through the environment: the layout at the start of each turn is
    # the hidden truth the note should be compared against.
    ep = Episode(config, result["seed"])
    board = ep.board
    layouts: dict[int, list[str]] = {}
    for rec in data["records"]:
        layouts[rec["turn"]] = list(ep.layout)
        if rec.get("skipped"):
            ep.skip_turn(rec["skipped"])
        else:
            ep.apply(Action(presses=list(rec["presses"]),
                            locks=dict(rec.get("locks_accepted") or {})))
        got = ep.records[-1]
        if (got["results"] != rec["results"]
                or got["rotation"]["positions"] != rec["rotation"]["positions"]):
            raise SystemExit(f"replay diverged from the stored record at turn {rec['turn']}")
    final = {board.addresses[i]: ep.layout[i] for i in range(board.n)}
    if final != result["final_layout"]:
        raise SystemExit("replay does not reproduce the stored final layout")

    records = {rec["turn"]: rec for rec in data["records"]}
    turns = {t["turn"]: t for t in data["turns"]}
    batons = {b["turn"]: b for b in result["batons"]}
    panels = []
    for t in range(FIRST_TURN, FIRST_TURN + 3):
        turn, rec, prev = turns[t], records[t], records[t - 1]
        reply = extract_json(turn["replies"][-1]["text"])
        note = reply.get("note", "") if isinstance(reply, dict) else ""
        kept = note[:budget]
        if kept != turn["baton_out"]:
            raise SystemExit(f"turn {t}: reply note does not match the stored baton")
        if ", ".join(prev["results"]) not in turn["user"]:
            raise SystemExit(f"turn {t}: observation text does not carry the stored results")
        pins, sets = parse_note(kept, board)
        truth = layouts[t]
        wrong = {board.addresses[p]: s for p, s in pins.items() if truth[p] != s}
        if wrong:
            raise SystemExit(f"turn {t}: note pins disagree with the hidden layout: {wrong}")
        for pos, syms in sets.items():
            if truth[pos] not in syms.split("/"):
                raise SystemExit(f"turn {t}: set fact on {board.addresses[pos]} is false")
        panels.append({
            "turn": t,
            "note_in_torn": batons[t - 1]["truncated"],
            "obs_presses": [abbr(a) for a in prev["presses"]],
            "obs_results": list(prev["results"]),
            "obs_rotated": [abbr(a) for a in (prev["rotation"].get("addresses") or [])],
            "presses": [abbr(a) for a in rec["presses"]],
            "pressed": set(rec["press_positions"]),
            # the keys this turn's rotation notice names (moved since last turn),
            # so every color on a board matches text in the same column
            "rotated": set(prev["rotation"]["positions"]),
            "kept": kept,
            "overflow": note[budget:],
            "pins": pins,
            "sets": sets,
            "truth": truth,
        })
    return {"board": board, "budget": budget, "seed": result["seed"],
            "model": result["model"], "panels": panels}


def load_regimes() -> dict:
    """nano's B=100 note cell and both transcript controls, through the
    ladder table's own loader; gaps are paired on shared seeds."""
    from relay_analysis import load_cells

    cells, _ = load_cells()
    keys = {"note": ("nano", "freeform", "std", "100"),
            "visible": ("nano", "freeform", "std", "full"),
            "retained": ("nano", "freeform", "std", "retained")}
    acc = {k: {s: r["board_accuracy"] for s, r in cells[v].items()} for k, v in keys.items()}
    for k, seeds in acc.items():
        if not seeds:
            raise SystemExit(f"no stored episodes for nano's {k} cell")

    def paired_gap(a: str, b: str) -> float:
        shared = sorted(set(acc[a]) & set(acc[b]))
        return sum(acc[b][s] - acc[a][s] for s in shared) / len(shared)

    return {"mean": {k: sum(v.values()) / len(v) for k, v in acc.items()},
            "n": {k: len(v) for k, v in acc.items()},
            "gap_history": paired_gap("note", "visible"),
            "gap_reasoning": paired_gap("visible", "retained")}


def fmt3(x: float) -> str:
    """The tables' number style: .286, never 0.286."""
    s = f"{x:.3f}"
    return s.replace("0.", ".", 1) if s.lstrip("-").startswith("0.") else s


# ----------------------------------------------------------------- drawing

def box(ax, x, y, w, h, face=PANEL, edge=EDGE, lw=0.6, r=0.035, z=1):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                facecolor=face, edgecolor=edge, linewidth=lw, zorder=z))


def arrow_path(ax, verts, color=TEXT, lw=0.9, ls="-", head=True, z=6):
    codes = [MPath.MOVETO] + [MPath.LINETO] * (len(verts) - 1)
    ax.add_patch(FancyArrowPatch(path=MPath(verts, codes),
                                 arrowstyle="-|>" if head else "-", mutation_scale=6,
                                 color=color, linewidth=lw, linestyle=ls,
                                 shrinkA=0, shrinkB=0, zorder=z))


def cross(ax, x, y, s=0.035, color=LOST, lw=1.3, z=8):
    ax.plot([x - s, x + s], [y - s, y + s], color=color, lw=lw, solid_capstyle="round", zorder=z)
    ax.plot([x - s, x + s], [y + s, y - s], color=color, lw=lw, solid_capstyle="round", zorder=z)


def cloud(ax, cx, cy, w, h, z=5):
    """A thought bubble: overlapping lobes around an ellipse."""
    lobes = [(-0.36, 0.10, 0.34), (-0.10, 0.22, 0.36), (0.18, 0.20, 0.34), (0.38, 0.02, 0.30),
             (0.20, -0.20, 0.32), (-0.08, -0.22, 0.34), (-0.36, -0.12, 0.30)]
    for dx, dy, r in lobes:
        ax.add_patch(Ellipse((cx + dx * w, cy + dy * h), r * w * 1.2, r * h * 2.4,
                             facecolor=PAPER, edgecolor=TEXT2, linewidth=0.6, zorder=z))
    ax.add_patch(Ellipse((cx, cy), w * 0.86, h * 0.80, facecolor=PAPER, edgecolor="none",
                         zorder=z + 0.1))


def keyboard(ax, board, x0, y_top, pitch, truth, pins, sets, pressed, rotated):
    """26-key board in finger columns (the address scheme), walkthrough style."""
    size = pitch * 0.88
    gap = pitch * 0.30  # between the hands
    columns = [idx for _label, idx, _rows in board.column_groups]
    for col, indices in enumerate(columns):
        x = x0 + col * pitch + (gap if col >= len(columns) // 2 else 0.0)
        for pos in indices:
            row = ROWS3.index(board.addresses[pos].split("-")[2])
            y = y_top - (row + 1) * pitch
            face, edge, lw = KEYFACE, EDGE, 0.5
            if pos in rotated:
                face, edge, lw = "#fbe3d6", ROTATE, 0.9
            if pos in pressed:
                edge, lw = PRESS, 1.25
            ax.add_patch(FancyBboxPatch((x, y), size, size,
                                        boxstyle=f"round,pad=0,rounding_size={size * 0.16}",
                                        facecolor=face, edgecolor=edge, linewidth=lw, zorder=3))
            cx, cy = x + size / 2, y + size * 0.52
            if pos in pins:
                ax.text(cx, cy, pins[pos], fontsize=7.4, color=DEDUCE, fontweight="bold",
                        ha="center", va="center", zorder=4)
            elif pos in sets:
                ax.text(cx, cy, sets[pos], fontsize=4.6, color=DEDUCE, ha="center",
                        va="center", zorder=4)
            else:
                ax.text(cx, cy, "?", fontsize=5.8, color=MUTED, ha="center", va="center", zorder=4)
            ax.text(x + size * 0.83, y + size * 0.15, truth[pos], fontsize=4.2, color=TRUTH,
                    ha="center", va="center", zorder=4)
        finger = board.addresses[indices[0]].split("-")[1]
        ax.text(x + size / 2, y_top - 3 * pitch - 0.035, FINGER_ABBR[finger], fontsize=5,
                color=TEXT2, ha="center", va="top")
    for row, name in enumerate(ROWS3):
        ax.text(x0 - 0.04, y_top - (row + 0.5) * pitch + 0.005, ROW_ABBR[name], fontsize=5,
                color=TEXT2, ha="right", va="center")


def note_card(ax, x, y_top, text, overflow, budget, fs=CARD_FS, per_row=CARD_ROW):
    """The note as a card of `budget` character cells; anything past the
    budget hangs below a torn edge. Returns the card's right edge."""
    cw = MONO_ADVANCE * fs / 72 * 1.04
    rh = fs * 1.34 / 72
    rows = -(-budget // per_row)
    pad = 0.028
    w, h = per_row * cw + 2 * pad, rows * rh + 2 * pad
    torn = bool(overflow)
    x1, y1 = x + w, y_top - h
    if torn:  # zig-zag bottom edge
        teeth = 22
        edge = [(x + i * w / teeth, y1 + (0.018 if i % 2 else 0.0)) for i in range(teeth + 1)]
        poly = [(x, y_top), (x1, y_top)] + edge[::-1]
        ax.add_patch(Polygon(poly, closed=True, facecolor=PAPER, edgecolor=EDGE, linewidth=0.6,
                             zorder=3))
    else:
        ax.add_patch(FancyBboxPatch((x, y1), w, h, boxstyle="round,pad=0,rounding_size=0.02",
                                    facecolor=PAPER, edgecolor=EDGE, linewidth=0.6, zorder=3))
    # The character ruler: faint cell grid, heavier every 5 cells.
    for c in range(1, per_row):
        xx = x + pad + c * cw
        ax.plot([xx, xx], [y_top - pad, y1 + pad + (0.018 if torn else 0)],
                color="#e9e7e1" if c % 5 else "#dcdad3", lw=0.35, zorder=3.5)
    for r in range(1, rows):
        yy = y_top - pad - r * rh
        ax.plot([x + pad, x1 - pad], [yy, yy], color="#e9e7e1", lw=0.35, zorder=3.5)
    for i, ch in enumerate(text):
        r, c = divmod(i, per_row)
        ax.text(x + pad + (c + 0.5) * cw, y_top - pad - (r + 0.52) * rh, ch, fontsize=fs,
                family=MONO, color=TEXT, ha="center", va="center", zorder=4)
    for r in range(rows):
        ax.text(x1 + 0.025, y_top - pad - (r + 0.52) * rh, str(min((r + 1) * per_row, budget)),
                fontsize=6.0, color=TEXT2, ha="left", va="center", zorder=4)
    if torn:
        # the lost scrap, hanging below the tear
        sy = y1 - 0.05
        sw = len(overflow) * cw + 2 * pad
        zig = [(x + 0.02 + i * sw / 6, sy + (0.014 if i % 2 else 0.0)) for i in range(7)]
        scrap = zig + [(x + 0.02 + sw, sy - rh - 0.01), (x + 0.02, sy - rh - 0.01)]
        ax.add_patch(Polygon(scrap, closed=True, facecolor="#fbeeec", edgecolor=LOST,
                             linewidth=0.5, linestyle=(0, (2, 1.2)), zorder=3))
        for i, ch in enumerate(overflow):
            ax.text(x + 0.02 + pad + (i + 0.5) * cw, sy - rh * 0.52, ch, fontsize=fs, family=MONO,
                    color=LOST, ha="center", va="center", zorder=4)
        ax.text(x + 0.02, sy - rh - 0.085, f"beyond {budget}: discarded",
                fontsize=6.8, color=LOST, ha="left", va="center", zorder=4)
    return x1


def card_rows_h(budget: int) -> float:
    """Height of a note card (inches) for the given budget."""
    return -(-budget // CARD_ROW) * CARD_FS * 1.34 / 72 + 2 * 0.028


def fig_loop(d: dict):
    board, budget, panels = d["board"], d["budget"], d["panels"]
    colw = W / 3
    m = 0.10  # column inner margin; the turn boundary sits between columns
    pitch = 0.166  # keyboard key pitch

    # Vertical layout, inches below the top edge.
    y_head = 0.075
    sees_top = 0.165
    sees_rows = (0.09, 0.24, 0.38, 0.52, 0.67)  # rules, chord, results, rotation, note
    sees_h = 0.77
    cloud_y = sees_top + sees_h + 0.15
    writes_top = sees_top + sees_h + 0.30
    writes_rows = (0.10, 0.26)  # WRITES + presses, note label
    card_top = writes_top + 0.345
    card_h = card_rows_h(budget)
    torn_any = any(p["overflow"] for p in panels)
    scrap_h = (0.05 + CARD_FS * 1.34 / 72 + 0.145) if torn_any else 0.0
    writes_h = card_top - writes_top + card_h + scrap_h + 0.055
    grid_top = writes_top + writes_h + 0.075
    grid_bottom = grid_top + 3 * pitch + 0.11  # finger labels included
    H = grid_bottom + 0.17

    fig = plt.figure(figsize=(W, H), facecolor=SURFACE)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_aspect("equal")
    ax.axis("off")

    def Y(off):  # inches below the top edge -> data y
        return H - off

    note_line = sees_top + sees_rows[4]
    for i, p in enumerate(panels):
        x0 = i * colw + m
        inner_w = colw - 2 * m
        wall_x = (i + 1) * colw
        ax.text(x0, Y(y_head), f"Turn {p['turn']}", fontsize=8.2, color=TEXT, fontweight="bold",
                ha="left", va="center")
        ax.text(x0 + 0.47, Y(y_head), "a fresh context", fontsize=7.4, color=TEXT2,
                ha="left", va="center")

        # --- what the instance sees
        box(ax, x0, Y(sees_top + sees_h), inner_w, sees_h)
        lx = x0 + 0.055
        tx = lx + 0.30  # text column after the SEES / WRITES label
        ax.text(lx, Y(sees_top + sees_rows[0]), "SEES", fontsize=6.8, color=TEXT2, ha="left",
                va="center", fontweight="bold")
        ax.text(tx, Y(sees_top + sees_rows[0]), "the rules (same every turn)", fontsize=FS,
                color=TEXT, ha="left", va="center")
        chord = " ".join(p["obs_presses"])
        results = ",".join(p["obs_results"])
        ax.text(lx, Y(sees_top + sees_rows[1]), f"last chord {chord}",
                fontsize=FS, color=TEXT, ha="left", va="center")
        ax.text(lx, Y(sees_top + sees_rows[2]), f"symbols {{{results}}} (unordered)",
                fontsize=FS, color=TEXT, ha="left", va="center")
        ax.text(lx, Y(sees_top + sees_rows[3]), "rotated: " + " ".join(p["obs_rotated"]),
                fontsize=FS, color=ROTATE, ha="left", va="center")
        torn_tag = " (cut)" if p["note_in_torn"] else ""
        ax.text(lx, Y(note_line), f"note from turn {p['turn'] - 1}{torn_tag}",
                fontsize=FS, color=TEXT, ha="left", va="center", fontweight="bold")

        # --- reasoning: private to the turn, discarded at the boundary
        arrow_path(ax, [(x0 + 0.30, Y(sees_top + sees_h)), (x0 + 0.30, Y(writes_top))],
                   color=TEXT2, lw=0.8)
        cx, cy = x0 + 0.98, Y(cloud_y)
        cloud(ax, cx, cy, 0.60, 0.18)
        ax.text(cx, cy, "reasoning", fontsize=FS, color=TEXT2, style="italic", ha="center",
                va="center", zorder=7)
        for k, (dx, r) in enumerate(((-0.44, 0.022), (-0.53, 0.015))):
            ax.add_patch(Circle((cx + dx, cy - 0.06 - k * 0.02), r, facecolor=PAPER,
                                edgecolor=TEXT2, linewidth=0.5, zorder=5))
        stop = min(wall_x, W - 0.04)  # the last boundary is the figure edge
        arrow_path(ax, [(cx + 0.33, cy), (stop - 0.05, cy)], color=LOST, lw=0.8,
                   ls=(0, (2.5, 1.5)), head=False)
        cross(ax, stop - 0.02, cy)
        ax.text(stop - 0.07, cy + 0.07, "discarded", fontsize=6.8, color=LOST, ha="right",
                va="bottom")

        # --- what it writes
        box(ax, x0, Y(writes_top + writes_h), inner_w, writes_h)
        ax.text(lx, Y(writes_top + writes_rows[0]), "WRITES", fontsize=6.8, color=TEXT2,
                ha="left", va="center", fontweight="bold")
        ax.text(tx + 0.18, Y(writes_top + writes_rows[0]), " ".join(p["presses"]),
                fontsize=FS, color=PRESS, ha="left", va="center")
        ax.text(lx, Y(writes_top + writes_rows[1]), f"note: at most {budget} characters",
                fontsize=FS, color=TEXT, ha="left", va="center")
        right = note_card(ax, lx, Y(card_top), p["kept"], p["overflow"], budget)

        # --- the note is the one thing that crosses into the next turn
        row_h = CARD_FS * 1.34 / 72
        card_mid = Y(card_top + 0.028 + 2 * row_h)  # between rows 2 and 3
        start = right + 0.15  # clear of the ruler numbers
        if i < 2:
            nxt = (i + 1) * colw + m
            arrow_path(ax, [(start, card_mid), (wall_x + 0.045, card_mid),
                            (wall_x + 0.045, Y(note_line)), (nxt, Y(note_line))],
                       color=TEXT, lw=1.1)
        else:
            lower_y = Y(writes_top + writes_h - 0.095)
            arrow_path(ax, [(lx + 0.88, Y(card_top + card_h)),
                            (lx + 0.88, lower_y + 0.075)], color=TEXT, lw=1.1)
            ax.text(lx, lower_y, f"note continues to turn {p['turn'] + 1}", fontsize=6.8,
                    color=TEXT2, ha="left", va="center")

        # --- the board: what this note says, against the hidden truth
        keyboard(ax, board, x0 + 0.13, Y(grid_top), pitch, p["truth"], p["pins"], p["sets"],
                 p["pressed"], p["rotated"])
        ax.text(x0, Y(grid_bottom + .08), "gray = analyst-only truth", fontsize=7.3,
                color=TEXT2, va="center")

    # the first panel's note arrives from turn FIRST_TURN - 1
    arrow_path(ax, [(0.0, Y(note_line)), (m, Y(note_line))], color=TEXT, lw=1.1)
    # the turn boundaries: the context is rebuilt from scratch on the far side
    for k in (1, 2):
        ax.plot([k * colw, k * colw], [Y(0.0), Y(grid_bottom)], color="#c9c7c0",
                lw=0.7, linestyle=(0, (3, 2)), zorder=0.5)
        ax.text(k * colw, Y(grid_top + 1.5 * pitch), "new context", fontsize=6.8, color=TEXT2,
                rotation=90, ha="center", va="center", zorder=1,
                bbox={"boxstyle": "square,pad=0.15", "facecolor": SURFACE, "edgecolor": "none"})
    return fig


def icon_card(ax, x, y, z=4):
    """A tiny note card (the baton)."""
    w, h = 0.15, 0.085
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                boxstyle="round,pad=0,rounding_size=0.012",
                                facecolor=PAPER, edgecolor=TEXT2, linewidth=0.6, zorder=z))
    for k in (0.018, -0.012):
        ax.plot([x - w / 2 + 0.022, x + w / 2 - 0.03 - (0.03 if k < 0 else 0)], [y + k, y + k],
                color=TEXT2, lw=0.5, zorder=z + 0.1)


def icon_transcript(ax, x, y, z=4):
    """A tiny stacked transcript: every earlier observation and reply."""
    w, h = 0.13, 0.10
    for k, dz in ((0.024, 0.0), (0.012, 0.1), (0.0, 0.2)):
        ax.add_patch(FancyBboxPatch((x - w / 2 + k, y - h / 2 - k), w, h,
                                    boxstyle="round,pad=0,rounding_size=0.012",
                                    facecolor=PAPER, edgecolor=TEXT2, linewidth=0.55,
                                    zorder=z + dz))
    for k in (0.025, 0.0, -0.025):
        ax.plot([x - w / 2 + 0.02, x + w / 2 - 0.02], [y + k, y + k], color=TEXT2, lw=0.45,
                zorder=z + 0.3)


def fig_regimes(r: dict):
    label_w = 1.72
    colw = (W - label_w) / 3
    rows_y = (0.235, 0.385, 0.535)  # inches below the top
    score_y = 0.785
    H = 1.16
    fig = plt.figure(figsize=(W, H), facecolor=SURFACE)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_aspect("equal")
    ax.axis("off")

    def Y(off):
        return H - off

    ns = sorted(set(r["n"].values()))
    n_txt = f"n = {ns[0]} seeds each" if len(ns) == 1 else "n = " + "/".join(
        str(r["n"][k]) for k in ("note", "visible", "retained"))
    labels = ("predecessor's note (≤ B chars)",
              "earlier observations and replies",
              "earlier reasoning")
    ax.text(0.0, Y(0.075), "what else reaches turn t", fontsize=FS, color=TEXT2, ha="left",
            va="center", style="italic")
    for label, yy in zip(labels, rows_y):
        ax.text(0.0, Y(yy), label, fontsize=FS, color=TEXT, ha="left", va="center")
    ax.text(0.0, Y(score_y), f"nano's mean accuracy\n({n_txt})", fontsize=FS,
            color=TEXT, ha="left", va="center", fontweight="bold")

    # (crosses?) per row: note, history, reasoning; None = no such channel
    regimes = (("note", "relay note, B = 100", (True, False, False)),
               ("visible", "visible transcript", (None, True, False)),
               ("retained", "retained transcript", (None, True, True)))
    icons = (icon_card, icon_transcript, lambda a, x, y: cloud(a, x, y, 0.19, 0.075, z=4))
    centers = []
    for j, (key, title, crosses) in enumerate(regimes):
        c0 = label_w + j * colw
        wall = c0 + colw * 0.55
        centers.append(wall)
        ax.text(wall, Y(0.075), title, fontsize=7.4, color=TEXT, fontweight="bold",
                ha="center", va="center")
        ax.plot([wall, wall], [Y(rows_y[0] - 0.075), Y(rows_y[-1] + 0.075)], color="#c9c7c0",
                lw=0.7, linestyle=(0, (3, 2)), zorder=0.5)
        for yy, flag, draw in zip(rows_y, crosses, icons):
            ix = wall - 0.33
            if flag is None:
                ax.text(ix, Y(yy), "no note", fontsize=7.0, color=TEXT2, ha="center",
                        va="center", style="italic")
                continue
            draw(ax, ix, Y(yy))
            if flag:
                arrow_path(ax, [(ix + 0.12, Y(yy)), (wall + 0.30, Y(yy))], color=TEXT, lw=1.0)
            else:
                arrow_path(ax, [(ix + 0.12, Y(yy)), (wall - 0.04, Y(yy))], color=LOST, lw=0.8,
                           ls=(0, (2.5, 1.5)), head=False)
                cross(ax, wall - 0.01, Y(yy), s=0.028, lw=1.2)
        ax.text(wall, Y(score_y), fmt3(r["mean"][key]), fontsize=7.6, color=TEXT,
                fontweight="bold", ha="center", va="center")
    # Historical differences are descriptive, not a causal decomposition.
    for (a, b), gap in zip(((0, 1), (1, 2)), (r["gap_history"], r["gap_reasoning"])):
        x_a, x_b = centers[a] + 0.19, centers[b] - 0.19
        ax.plot([x_a, x_b], [Y(score_y)] * 2, color=TEXT2, lw=0.7)
        ax.text((x_a + x_b) / 2, Y(score_y) + 0.03, "+" + fmt3(gap), fontsize=7.2,
                color=TEXT2, ha="center", va="bottom")
    for x, date in zip(centers, ("Jul / Sep", "July", "25 Sep")):
        ax.text(x, Y(.92), date, fontsize=7.4, color=TEXT2, ha="center", va="center")
    ax.text(0, Y(1.08), "Historical descriptive means; retained controls were collected later",
            fontsize=7.8, color=TEXT2, va="center")
    return fig


def report(d: dict, r: dict) -> None:
    """Print what the figures were built from, for the build log."""
    print(f"episode: {EPISODE.relative_to(ROOT)} ({d['model']}, B={d['budget']}, "
          f"seed {d['seed']}); replay matches every stored record")
    for p in d["panels"]:
        pins = ", ".join(f"{abbr(d['board'].addresses[k])}={v}" for k, v in sorted(p["pins"].items()))
        print(f"  turn {p['turn']}: {len(p['kept'])} chars kept, {len(p['overflow'])} torn off; "
              f"pins [{pins}] all match the hidden layout")
    print("nano B=100: " + ", ".join(f"{k} {fmt3(v)} (n={r['n'][k]})" for k, v in r["mean"].items())
          + f"; paired gaps +{fmt3(r['gap_history'])} history, +{fmt3(r['gap_reasoning'])} reasoning")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    episode, regimes = load_episode(), load_regimes()
    report(episode, regimes)
    for name, fig in (("relay_figA_loop", fig_loop(episode)),
                      ("relay_figA_regimes", fig_regimes(regimes))):
        for ext, meta in (("svg", {"Date": None}), ("pdf", {"CreationDate": None}), ("png", {})):
            # no timestamps: rebuilding from the same data gives the same bytes
            fig.savefig(OUT / f"{name}.{ext}", dpi=300 if ext == "png" else 170,
                        facecolor=SURFACE, metadata=meta)
        plt.close(fig)
        print(f"wrote paper/figures/{name}.{{svg,pdf,png}}")


if __name__ == "__main__":
    main()
