"""Blindboard: Relay — the memory-channel track.

Same certified game as Blindboard; different physics of memory. Each turn
is a FRESH model instance (no transcript): the only bridge across turns is
a baton the model authors under a character budget. Measures memory
engineering — state compression, notation invention, self-communication —
where Blindboard-R1 measures in-context state tracking.

SEPARATION CONTRACT (so this track can be split into its own repo later):
- relay/* imports from blindboard/*; nothing in blindboard/* imports relay.
- Relay entry points live in scripts/relay_*.py only.
- Relay artifacts write to results/relay/ only.
- Relay tests live in tests/test_relay.py only.
- Docs: docs/relay-design.md.
To extract: move relay/, scripts/relay_*.py, tests/test_relay.py,
docs/relay-design.md, results/relay/ to a new repo and depend on
blindboard as a library (or vendor it).
"""

__version__ = "0.1.0"
