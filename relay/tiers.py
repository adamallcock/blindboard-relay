"""Relay track configurations: a base game + a memory-channel budget."""

from __future__ import annotations

from dataclasses import dataclass, field

from blindboard.env import EnvConfig

# Base game for the relay pilot: 26 keys, announced churn decaying to zero
# by turn 9, horizon 20 — R1-reference-solvable with slack, so channel
# effects are attributable to the channel.
RELAY_BASE = EnvConfig(
    board="qwerty26",
    chord_size=4,
    horizon=20,
    rotation_mode="announced",
    rotation_schedule=(3, 3, 3, 3, 2, 2, 2, 2),
)

# Long-horizon variant for drift-rate measurement: churn ends by turn 9,
# then 52 static turns — any late degradation is channel, not world.
RELAY_BASE_LONG = EnvConfig(
    board="qwerty26",
    chord_size=4,
    horizon=60,
    rotation_mode="announced",
    rotation_schedule=(3, 3, 3, 3, 2, 2, 2, 2),
)

# 39-key base for the schema-transfer check (does the harness generalize?).
RELAY_BASE39 = EnvConfig(
    board="qwerty39",
    chord_size=4,
    horizon=24,
    rotation_mode="announced",
    rotation_schedule=(3, 3, 3, 3, 2, 2, 2, 2),
)

BASES = {"std": RELAY_BASE, "long": RELAY_BASE_LONG, "numrow": RELAY_BASE39}

# Character budgets for the pilot grid (constant per episode). The
# budget-matched reference calibration tells us where a sound encoder's
# knee sits; these bracket it.
BUDGETS = (800, 400, 200, 100, 50)


@dataclass(frozen=True)
class RelayConfig:
    base: EnvConfig = field(default_factory=lambda: RELAY_BASE)
    budget_chars: int = 400
    # Memory-support ladder: freeform (L1) | schema (L2, notation in rules) |
    # constitution (L3, self-designed spec pinned every turn) | form (L4,
    # harness-validated structured memory).
    condition: str = "freeform"
    # Optional per-turn budgets (the "vanishing notepad"); overrides
    # budget_chars when set. Index t-1 = budget for the note written on
    # press turn t; missing entries fall back to the last value.
    budget_schedule: tuple[int, ...] | None = None
    # Rules-text variant: "v2" (the printed grid) or "nocoach" (v2 minus the
    # notation/content coaching sentences — the instrument-audit control).
    prompt_variant: str = "v2"

    def budget_for_turn(self, turn: int) -> int:
        if self.budget_schedule:
            idx = min(turn - 1, len(self.budget_schedule) - 1)
            return self.budget_schedule[idx]
        return self.budget_chars


# The dramatic single tier: paper shrinks as the game converges.
VANISHING = RelayConfig(
    base=RELAY_BASE,
    budget_schedule=(600, 500, 400, 320, 250, 200, 160, 120, 100, 80, 70, 60, 55, 50, 45, 40, 35, 30, 25, 20),
)
