"""L4 memory harness: validated structured memory, harness-rendered.

The model submits {"mem": {"known": {addr: SYM}, "groups": [{"keys": [...],
"syms": "..."}]}}; the harness validates entries (invalid ones dropped),
renders them in a fixed compact format, and that rendering IS the baton.
Schema discipline is enforced by protocol, not by the model's own
consistency — the top rung of the memory-support ladder."""

from __future__ import annotations

from typing import Any

from blindboard.boards import Board

_REACH = {"in": "i", "out": "o", "o1": "1", "o2": "2", "o3": "3"}


def short_code(address: str) -> str:
    parts = address.split("-")
    hand, finger, row = parts[0], parts[1], parts[2]
    suffix = _REACH.get(parts[3], "?") if len(parts) > 3 else ""
    return f"{hand}{finger[0].upper()}{row[0]}{suffix}"


def render_mem(mem: Any, board: Board, budget: int) -> tuple[str, int, int]:
    """Validate + render the structured memory. Returns (baton, invalid,
    overflow): `invalid` counts entries dropped by validation, `overflow`
    counts valid entries that did not fit the budget — the two are
    different failure modes (compliance vs capacity) and must not be
    conflated in analysis. Known entries first (in submitted order), then
    groups; rendering stops at the last whole entry that fits."""
    if not isinstance(mem, dict):
        return "", 1, 0
    lookup = {a.lower(): a for a in board.addresses}
    invalid = 0
    overflow = 0
    entries: list[str] = []

    known = mem.get("known") or {}
    if isinstance(known, dict):
        for raw, sym in known.items():
            addr = lookup.get(str(raw).strip().lower().replace("_", "-").replace(" ", "-"))
            symbol = str(sym).strip().upper() if isinstance(sym, str) else ""
            if addr is None or symbol not in board.symbols:
                invalid += 1
                continue
            entries.append(f"{short_code(addr)}={symbol}")
    else:
        invalid += 1

    group_entries: list[str] = []
    groups = mem.get("groups") or []
    if isinstance(groups, list):
        for g in groups:
            if not isinstance(g, dict):
                invalid += 1
                continue
            keys = g.get("keys") or []
            syms = str(g.get("syms", "")).strip().upper()
            addrs = []
            for raw in keys if isinstance(keys, list) else []:
                addr = lookup.get(str(raw).strip().lower().replace("_", "-").replace(" ", "-"))
                if addr is not None:
                    addrs.append(addr)
            if (
                len(addrs) >= 2
                and len(set(addrs)) == len(addrs)
                and len(syms) == len(addrs)
                and all(s in board.symbols for s in syms)
            ):
                group_entries.append("+".join(short_code(a) for a in addrs) + "=" + syms)
            else:
                invalid += 1
    else:
        invalid += 1

    baton = ""
    for prefix, pool in (("K ", entries), ("G ", group_entries)):
        section = ""
        for e in pool:
            candidate = (section + " " if section else prefix) + e
            base = baton + (" | " if baton and not section else "")
            if len(base + candidate) <= budget:
                section = candidate
            else:
                overflow += 1
        if section:
            baton = baton + (" | " if baton else "") + section
    return baton, invalid, overflow
