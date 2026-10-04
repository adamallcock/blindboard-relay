"""Prompts for the relay track: brutal, believable amnesia."""

from __future__ import annotations

from blindboard.env import Observation
from blindboard.prompts import build_system_prompt, format_observation
from relay.tiers import RelayConfig

RELAY_RULES = """

RELAY MODE — READ CAREFULLY
You have NO memory of previous turns. Every turn is played by a fresh
instance of you: this message is literally everything you know. There is
no transcript and no way to see past observations.

The ONLY thing that survives between turns is a NOTE that you write. The
note you receive below was written by you, one turn ago, for you. The note
you write now is the only information your next turn's self will have
(besides these rules and that turn's fresh observation).

Notes do NOT accumulate: your successor receives ONLY the single note you
write this turn. The note shown below is destroyed after this turn —
whatever from it still matters must be carried in your own note.

Your successor's observation will automatically include the presses you
make this turn, the symbols they produce, and any rotation notice —
exactly like the observation you see below.

Add a "note" field to your action JSON: {{"presses": [...], "note": "..."}}.
HARD LIMIT: this turn's note budget is {budget} characters — anything
beyond that is torn off and lost forever. Do not waste characters on
prose, apologies, or restating the rules (your successor has the rules).
Invent the densest notation you can and keep it consistent so your future
self can decode it. Record what matters: what you know about the layout,
what is still uncertain, and what you were planning.
"""

PROMPT_VERSION = "relay-v2"

# The final two sentences of the v2 rules instruct notation density,
# cross-turn consistency, and state-first content — behaviors the paper
# also measures. The "nocoach" variant removes them (mechanics only), so
# the coaching effect is itself a measured instrument-audit quantity
# rather than a confound.
COACHING_SENTENCES = (
    "Invent the densest notation you can and keep it consistent so your future\n"
    "self can decode it. Record what matters: what you know about the layout,\n"
    "what is still uncertain, and what you were planning.\n"
)
RELAY_RULES_NOCOACH = RELAY_RULES.replace(COACHING_SENTENCES, "")
assert RELAY_RULES_NOCOACH != RELAY_RULES, "coaching block drifted out of RELAY_RULES"

PROMPT_VERSIONS = {"v2": PROMPT_VERSION, "nocoach": "relay-v3-nocoach"}


def prompt_version_for(variant: str) -> str:
    return PROMPT_VERSIONS[variant]


def rules_for(variant: str) -> str:
    return RELAY_RULES if variant == "v2" else RELAY_RULES_NOCOACH

SCHEMA_DOC = """

NOTE NOTATION (required)
Write your note in this exact notation. Keys are numbered in the order of
the address list above: {key_range} (so key 0 = the first address, key a
= the 11th). Two entry types, concatenated with no spaces:
  !<key><SYM><key><SYM>...   known keys, e.g. !3Q7A means key 3 = Q, key 7 = A
  |<keys>:<SYMS>             a set fact, e.g. |58h:BKM means keys 5,8,h hold {{B,K,M}} in some order
Example note: !3Q7A|58h:BKM
"""


def _key_range_text(n: int) -> str:
    from relay.codec import POS_ALPHABET

    chars = POS_ALPHABET[:n]
    parts = []
    for start, end in (("0", "9"), ("a", "z"), ("A", "K")):
        seg = [c for c in chars if start <= c <= end and (c.isdigit() if start == "0" else c.islower() if start == "a" else c.isupper())]
        if seg:
            parts.append(f"{seg[0]}-{seg[-1]}" if len(seg) > 1 else seg[0])
    return " then ".join(parts)

CONSTITUTION_PROMPT = (
    "Before the game begins, design the note-taking notation you will use to "
    "communicate with your future self (your note budget will be {budget} "
    "characters per turn). Reply with ONLY the specification of your notation "
    "(max 400 characters). It will be shown back to you, verbatim, on every "
    "turn of the game — so it does not consume your note budget."
)

FORM_RULES = """

STRUCTURED MEMORY (instead of a free-text note)
Do not write a "note". Instead include a "mem" object in your action JSON:
  "mem": {{"known": {{"<address>": "<SYMBOL>", ...}},
           "groups": [{{"keys": ["<address>", ...], "syms": "<SYMBOLS>"}}, ...]}}
"known"  = keys whose symbol you are certain of right now.
"groups" = sets of keys that hold a known set of symbols in unknown order.
The harness validates your entries (invalid addresses/symbols are dropped),
renders them in a fixed compact format, and delivers that rendering to your
next turn's self as the note. The same {budget}-character limit applies to
the rendering: known entries are kept first, then groups, in the order you
list them — prioritize accordingly. You must resubmit the full memory every
turn; anything you omit is forgotten.
"""


SVG_RULES = """

IMAGE NOTE (instead of a text note)
Your note to your future self is an IMAGE. Include an "svg" field in your
action JSON containing self-contained SVG source (max {max_bytes} bytes;
no scripts, links, or embedded images — shapes and text only). The harness
renders it to a {px}x{px} pixel image, and ONLY that rendered image is
shown to your next turn's self — never the SVG source. Design for
legibility after rendering: whatever your future self cannot read off the
pixels is lost.
"""


def relay_system_prompt(config: RelayConfig, constitution: str | None = None) -> str:
    budget = config.budget_chars if not config.budget_schedule else "shown each turn"
    if config.condition == "svg":
        from relay.svg_channel import MAX_SVG_BYTES, RENDER_PX

        base_rules = rules_for(config.prompt_variant).format(budget=budget)
        # Replace the text-note paragraph mechanics with the image channel.
        base_rules = base_rules.split('Add a "note" field')[0]
        return (
            build_system_prompt(config.base)
            + base_rules
            + SVG_RULES.format(max_bytes=MAX_SVG_BYTES, px=RENDER_PX)
        )
    prompt = build_system_prompt(config.base) + rules_for(config.prompt_variant).format(budget=budget)
    if config.condition == "schema":
        prompt += SCHEMA_DOC.format(key_range=_key_range_text(config.base.board_obj().n))
    elif config.condition == "form":
        prompt += FORM_RULES.format(budget=budget)
    elif config.condition == "constitution" and constitution:
        prompt += (
            "\n\nYOUR NOTATION SPECIFICATION (you designed this before the game; "
            "it is shown every turn and costs you nothing):\n<<<" + constitution + ">>>"
        )
    return prompt


def relay_turn_message(
    obs: Observation, config: RelayConfig, baton: str, truncated: bool
) -> str:
    lines = []
    if baton:
        marker = " (it exceeded the limit and was torn off mid-way)" if truncated else ""
        lines.append(f"YOUR NOTE FROM LAST TURN{marker}:\n<<<{baton}>>>")
    else:
        lines.append("YOUR NOTE FROM LAST TURN: (none — you left no note)")
    lines.append("")
    lines.append(format_observation(obs, config.base))
    budget = config.budget_for_turn(obs.turn)
    if obs.phase != "guess":
        if config.condition == "form":
            lines.append(
                f'Include your full "mem" object (rendering limit {budget} characters this turn).'
            )
        else:
            lines.append(
                f'Include your note for next turn: "note" (max {budget} characters this turn).'
            )
    return "\n".join(lines)
