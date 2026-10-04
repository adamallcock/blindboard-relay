"""Sound belief-state codec: the budget-matched reference's channel.

Serializes a BeliefTracker into a dense, deterministic string; truncation
at any entry boundary yields a strictly weaker but still SOUND state
(dropping facts is always sound). The full-serialization length is the
"sound encoder needs N chars" measurement that calibrates budget tiers.

Format (letter-only boards, n <= 36):
  !<pos><sym><pos><sym>...        deduced singletons (2 chars per fact)
  |<positions>:<symbols>          group constraints (symbols occupy positions)
Position index alphabet: 0-9 then a-z. Sections concatenated, groups sorted
for determinism. Example: "!3Q7A|58h:BKM" = pos3=Q, pos7=A, and {B,K,M}
occupy positions {5,8,17}.
"""

from __future__ import annotations

from blindboard.boards import Board
from blindboard.tracker import BeliefTracker

POS_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJK"
RESERVED = set("!|:?=")  # entry markers / unknown / positional marker
UNKNOWN = "?"


def _check_board(board: Board) -> None:
    if board.n > len(POS_ALPHABET):
        raise ValueError(f"codec supports up to {len(POS_ALPHABET)} keys, got {board.n}")
    bad = [s for s in board.symbols if len(s) != 1 or s in "!|:?"]
    if bad:
        raise ValueError(f"codec requires single-char symbols outside '!|:?'; got {bad}")


def serialize_positional(tracker: BeliefTracker) -> str:
    """Dense-state form: '=' + one char per key ('?' = unknown) + groups.
    26 keys of solved board = 27 chars vs 53 entry-form — the encoding
    sol invented; the reference adopts it (v2) to keep the certificate
    honest at small budgets."""
    deduced = tracker.deduced()
    body = "".join(deduced.get(p, UNKNOWN) for p in range(tracker.n))
    return "=" + body + _groups_section(tracker, set(deduced))


def _groups_section(tracker: BeliefTracker, deduced_set: set[int]) -> str:
    groups = []
    for pset, lset in tracker.groups:
        remaining = sorted(p for p in pset if p not in deduced_set)
        if len(remaining) < 2:
            continue
        pinned = {next(iter(tracker.cand[p])) for p in pset if p in deduced_set}
        letters = "".join(sorted(lset - pinned))
        if len(letters) != len(remaining):
            remaining = sorted(pset)
            letters = "".join(sorted(lset))
        groups.append("|" + "".join(POS_ALPHABET[p] for p in remaining) + ":" + letters)
    return "".join(sorted(groups, key=lambda g: (len(g), g)))


def serialize(tracker: BeliefTracker) -> str:
    """Shortest sound serialization: entry form vs positional form."""
    entry = serialize_entries(tracker)
    positional = serialize_positional(tracker)
    return positional if len(positional) < len(entry) else entry


def serialize_budgeted(tracker: BeliefTracker, budget: int, positional: bool = True) -> str:
    """Best sound encoding that FITS: prefer whichever full form fits (the
    shorter first); otherwise fall back to truncated entry form (positional
    form cannot be truncated without corrupting alignment).

    positional=False reproduces codec v1 (entry form only, pre-adoption of
    the flagship's positional string) — kept so both codec generations can
    be re-certified and archived."""
    entry = serialize_entries(tracker)
    if not positional:
        return entry if len(entry) <= budget else truncate(entry, budget)
    pos_form = serialize_positional(tracker)
    for candidate in sorted((entry, pos_form), key=len):
        if len(candidate) <= budget:
            return candidate
    return truncate(entry, budget)


def serialize_entries(tracker: BeliefTracker) -> str:
    """Sparse-state form: singletons first (densest), then groups."""
    _check_board(tracker.board)
    deduced = tracker.deduced()
    parts: list[str] = []
    if deduced:
        parts.append("!" + "".join(
            POS_ALPHABET[p] + deduced[p] for p in sorted(deduced)
        ))
    parts.append(_groups_section(tracker, set(deduced)))
    return "".join(parts)


def truncate(memo: str, budget: int) -> str:
    """Cut at the last complete entry boundary <= budget."""
    if len(memo) <= budget:
        return memo
    cut = memo[:budget]
    if cut.startswith("!"):
        bar = cut.find("|")
        if bar == -1:
            # Inside the singleton section: keep whole (pos,sym) pairs.
            usable = 1 + ((len(cut) - 1) // 2) * 2
            return cut[:usable]
    # Drop the trailing partial group entry.
    last_bar = cut.rfind("|")
    if last_bar == -1:
        usable = 1 + ((len(cut) - 1) // 2) * 2 if cut.startswith("!") else 0
        return cut[:usable]
    tail = cut[last_bar:]
    colon = tail.find(":")
    if colon != -1 and len(tail) - (colon + 1) == colon - 1:
        return cut  # trailing group happens to be complete
    return cut[:last_bar]


def deserialize(memo: str, board: Board) -> BeliefTracker:
    """Rebuild a tracker from a memo. Truncating a sound serialization keeps
    the decoded state sound. Malformed entries are skipped defensively,
    but valid-looking false facts cannot be detected without ground truth."""
    tracker = BeliefTracker(board)
    if not memo:
        return tracker
    body = memo
    if body.startswith("="):
        posstring = body[1 : 1 + board.n]
        body = body[1 + board.n :]
        if len(posstring) == board.n:  # corrupted/truncated -> ignore
            for p, sym in enumerate(posstring):
                if sym != UNKNOWN and sym in board.symbols and sym in tracker.cand[p]:
                    tracker.cand[p] = {sym}
    if body.startswith("!"):
        end = body.find("|")
        singles = body[1:end] if end != -1 else body[1:]
        body = body[end:] if end != -1 else ""
        for i in range(0, len(singles) - 1, 2):
            pos_c, sym = singles[i], singles[i + 1]
            if pos_c in POS_ALPHABET and sym in board.symbols:
                p = POS_ALPHABET.index(pos_c)
                if p < board.n and sym in tracker.cand[p]:
                    tracker.cand[p] = {sym}
    for entry in body.split("|"):
        if not entry or ":" not in entry:
            continue
        pos_s, sym_s = entry.split(":", 1)
        if len(pos_s) != len(sym_s) or len(pos_s) < 2:
            continue
        try:
            positions = [POS_ALPHABET.index(c) for c in pos_s]
        except ValueError:
            continue
        if any(p >= board.n for p in positions):
            continue
        if not all(s in board.symbols for s in sym_s):
            continue
        tracker._add_group(frozenset(positions), frozenset(sym_s))
    tracker.propagate()
    return tracker
