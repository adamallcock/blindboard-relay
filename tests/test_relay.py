"""Relay track: codec soundness, budget-matched reference, amnesiac runner."""

from __future__ import annotations

import json

from blindboard.boards import BOARDS
from blindboard.env import Episode
from blindboard.tracker import BeliefTracker
from relay.agents import MemoReferenceAgent
from relay.codec import deserialize, serialize, truncate
from relay.runner import run_relay_llm, run_relay_reference
from relay.tiers import RELAY_BASE, RelayConfig

BOARD = BOARDS["qwerty26"]


def _tracked_state() -> BeliefTracker:
    t = BeliefTracker(BOARD)
    t.observe_chord([0, 3, 7, 9], ["A", "F", "K", "Q"])
    t.observe_chord([0, 3, 12, 13], ["A", "F", "M", "Z"])
    t.cand[20] = {"B"}
    t.propagate()
    return t


def test_codec_roundtrip_preserves_knowledge() -> None:
    t = _tracked_state()
    memo = serialize(t)
    t2 = deserialize(memo, BOARD)
    assert t2.deduced() == t.deduced()
    for p in range(BOARD.n):
        assert t2.cand[p] >= t.cand[p] or t2.cand[p] == t.cand[p]
        # Roundtrip may only widen, never narrow beyond truth (soundness).


def test_truncation_is_sound_and_parseable() -> None:
    t = _tracked_state()
    memo = serialize(t)
    for budget in range(0, len(memo) + 2):
        cut = truncate(memo, budget)
        assert len(cut) <= budget or budget >= len(memo)
        t2 = deserialize(cut, BOARD)  # must never raise
        # Everything the truncated memo pins must be true in the original.
        for p, sym in t2.deduced().items():
            assert sym in t.cand[p]


def test_deserialize_survives_garbage() -> None:
    for garbage in ["", "!!", "!5", "|abc", "|ab:XYZ", "hello world", "!zZ|" , "!5Q|58:Q"]:
        deserialize(garbage, BOARD)  # must not raise


def test_memo_reference_matches_r1_at_generous_budget() -> None:
    config = RelayConfig(base=RELAY_BASE, budget_chars=1200)
    solved = 0
    for seed in range(4):
        result = run_relay_reference(config, seed)
        solved += result["board_accuracy"] == 1.0
        assert result["lock_wrong"] == 0
        assert result["needed_chars_max"] <= 1200, "budget never binding at 1200"
    assert solved >= 3, f"generous-budget memo reference should solve, got {solved}/4"


def test_memo_reference_degrades_at_tiny_budget() -> None:
    generous = sum(
        run_relay_reference(RelayConfig(base=RELAY_BASE, budget_chars=1200), s)["board_accuracy"]
        for s in range(3)
    )
    tiny = sum(
        run_relay_reference(RelayConfig(base=RELAY_BASE, budget_chars=10), s)["board_accuracy"]
        for s in range(3)
    )
    assert tiny < generous, "a 10-char baton must hurt a sound player"


class FakeRelayAdapter:
    """Legal round-robin player that writes 'N<turn>' notes; proves the
    runner passes batons and stays amnesiac."""

    def __init__(self, config: RelayConfig) -> None:
        self.board = config.base.board_obj()
        self.k = config.base.chord_size
        self.model, self.effort = "fake", "none"
        self.calls = 0
        self.usage_totals: dict[str, int] = {}
        self.seen_messages: list[list[str]] = []
        self.turn = 0

    def call_with_meta(self, messages):
        self.calls += 1
        self.seen_messages.append([m.text for m in messages])
        user = messages[-1].text
        if "final guess" in user or "MUST now submit" in user:
            syms = list(self.board.symbols)
            pairs = ", ".join(f'"{a}": "{syms[i]}"' for i, a in enumerate(self.board.addresses))
            return '{"guess": {' + pairs + '}}', {"reasoning": [], "usage": {}}
        addrs = [self.board.addresses[(self.turn * self.k + i) % self.board.n] for i in range(self.k)]
        self.turn += 1
        note = f"N{self.turn}" + "x" * 300  # deliberately over-budget
        return (
            json.dumps({"presses": addrs, "note": note}),
            {"reasoning": [], "usage": {"input_tokens": 1, "output_tokens": 1}},
        )


def test_relay_llm_runner_amnesia_and_baton(tmp_path) -> None:
    config = RelayConfig(base=RELAY_BASE, budget_chars=40)
    adapter = FakeRelayAdapter(config)
    result = run_relay_llm(adapter, config, seed=0, transcript_dir=tmp_path)
    # Amnesia: every call is exactly [system, user] (plus retry pairs never
    # triggered here) — no accumulating transcript.
    assert all(len(msgs) == 2 for msgs in adapter.seen_messages)
    # Batons flow: turn t+1's user message contains turn t's (truncated) note.
    assert "N1" in adapter.seen_messages[1][1]
    assert result["truncated_turns"] == config.base.horizon  # every note over budget
    assert all(b["kept_len"] <= 40 for b in result["batons"])
    saved = json.loads((tmp_path / "seed0000.json").read_text())
    assert saved["turns"][0]["baton_out"].startswith("N1")
    # And the previous-turn results still reach the fresh instance via obs.
    assert "letters" in adapter.seen_messages[1][1] or "symbols" in adapter.seen_messages[1][1]


def test_v2_prompt_states_channel_mechanics() -> None:
    from relay.prompts import relay_system_prompt
    p = relay_system_prompt(RelayConfig(base=RELAY_BASE, budget_chars=100))
    assert "do NOT accumulate" in p
    assert "automatically include the presses" in p


def test_schema_and_form_conditions_extend_prompt() -> None:
    from relay.prompts import relay_system_prompt
    schema = relay_system_prompt(RelayConfig(base=RELAY_BASE, condition="schema"))
    assert "NOTE NOTATION" in schema and "!3Q7A" in schema
    form = relay_system_prompt(RelayConfig(base=RELAY_BASE, condition="form"))
    assert "STRUCTURED MEMORY" in form and '"mem"' in form


def test_form_renderer_validates_and_truncates() -> None:
    from relay.form import render_mem, short_code
    assert short_code("L-pinky-top") == "LPt"
    assert short_code("R-index-home-in") == "RIhi"
    mem = {
        "known": {"L-pinky-top": "A", "l_ring_home": "f", "L-thumb-top": "Q", "L-middle-top": "ZZ"},
        "groups": [
            {"keys": ["L-index-top", "L-index-home"], "syms": "BK"},
            {"keys": ["L-index-top"], "syms": "B"},  # too small -> dropped
        ],
    }
    baton, invalid, overflow = render_mem(mem, BOARD, budget=200)
    assert "LPt=A" in baton and "LRh=F" in baton
    assert "LIt+LIh=BK" in baton
    assert invalid == 3 and overflow == 0  # bad addr, bad symbol, bad group
    tiny, tiny_invalid, tiny_overflow = render_mem(mem, BOARD, budget=12)
    assert len(tiny) <= 12 and tiny.startswith("K ")
    assert tiny_invalid == 3 and tiny_overflow > 0  # valid entries cut by capacity


def test_constitution_is_pinned_every_turn(tmp_path) -> None:
    config = RelayConfig(base=RELAY_BASE, budget_chars=60, condition="constitution")

    class ConstitutionAdapter(FakeRelayAdapter):
        def call_with_meta(self, messages):
            if "design the note-taking notation" in messages[-1].text:
                self.calls += 1
                return "MYSPEC: pos=sym csv", {"reasoning": [], "usage": {}}
            return super().call_with_meta(messages)

    adapter = ConstitutionAdapter(config)
    result = run_relay_llm(adapter, config, seed=0, transcript_dir=tmp_path)
    assert result["constitution"] == "MYSPEC: pos=sym csv"
    game_calls = [m for m in adapter.seen_messages if "design the note-taking" not in m[-1]]
    assert all("MYSPEC" in msgs[0] for msgs in game_calls), "spec pinned in every system prompt"


def test_codec_v2_positional_mode() -> None:
    from relay.codec import serialize, serialize_budgeted, serialize_positional
    t = BeliefTracker(BOARD)
    # Nearly solved board: positional form must win and fit tiny budgets.
    import random as _r
    layout = list(BOARD.symbols)
    _r.Random(1).shuffle(layout)
    for p in range(24):
        t.cand[p] = {layout[p]}
    t.propagate()
    full = serialize(t)
    assert full.startswith("="), "dense state must pick positional form"
    assert len(full) <= 1 + BOARD.n + 12
    memo = serialize_budgeted(t, 30)
    t2 = deserialize(memo, BOARD)
    assert len(t2.deduced()) >= 20, "positional form carries the state at B=30"
    for p, sym in t2.deduced().items():
        assert t.cand[p] == {sym}


def test_codec_v2_39key_board() -> None:
    from relay.codec import serialize, deserialize as des
    b39 = BOARDS["qwerty39"]
    t = BeliefTracker(b39)
    t.observe_chord([0, 5, 38], ["1", "Q", "="])
    t.cand[10] = {"3"}
    t.propagate()
    memo = serialize(t)
    t2 = des(memo, b39)
    assert t2.deduced() == t.deduced()


def test_svg_sanitizer_and_renderer() -> None:
    import shutil
    import pytest as _pytest
    from relay.svg_channel import render_svg, sanitize_svg
    good = '<svg width="64" height="64"><rect width="64" height="64" fill="white"/><text x="5" y="30">Q=3</text></svg>'
    clean = sanitize_svg(good)
    assert clean is not None and "xmlns" in clean
    assert sanitize_svg('<svg><script>alert(1)</script></svg>') is None
    assert sanitize_svg('<svg><image href="http://x/y.png"/></svg>') is None
    assert sanitize_svg("not svg at all") is None
    assert sanitize_svg('<svg>' + 'x' * 5000 + '</svg>') is None
    if shutil.which("qlmanage") is None:
        _pytest.skip("no qlmanage on this platform")
    png1, png2 = render_svg(clean), render_svg(clean)
    assert png1 is not None and png1 == png2, "renderer must be deterministic"


def test_svg_filter_rejects_event_handlers_and_animation() -> None:
    from relay.svg_channel import sanitize_svg
    assert sanitize_svg('<svg><text>Compare T2: old-only=LRt, new-only=LRh.</text></svg>') is not None
    for source in (
        '<svg onload="void(0)"></svg>',
        '<svg><text ONCLICK = "void(0)">A</text></svg>',
        '<svg><set attributeName="opacity" to="0" begin="1s"/></svg>',
        '<svg><animate attributeName="x" from="0" to="1"/></svg>',
        '<svg><animateMotion path="M0 0L1 1"/></svg>',
        '<svg><animateTransform attributeName="transform"/></svg>',
    ):
        assert sanitize_svg(source) is None


def test_svg_prompt_replaces_text_note_mechanics() -> None:
    from relay.prompts import relay_system_prompt
    p = relay_system_prompt(RelayConfig(base=RELAY_BASE, condition="svg"))
    assert "IMAGE NOTE" in p and '"svg"' in p
    assert '"note"' not in p, "text-note instructions must not leak into svg condition"
