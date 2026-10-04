"""Relay episode runners: budget-matched reference (scripted) and LLM.

The LLM loop sends a FRESH two-message context every turn — system rules +
(baton, current observation). Nothing else crosses the gap. Batons are
logged verbatim: they are the qualitative data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from blindboard.client import APIAdapter, Message
from blindboard.env import Episode
from blindboard.protocol import extract_json, parse_action
from blindboard.runner import diagnose
from relay.agents import MemoReferenceAgent
from relay.form import render_mem
from relay.prompts import (
    CONSTITUTION_PROMPT,
    PROMPT_VERSION,
    prompt_version_for,
    relay_system_prompt,
    relay_turn_message,
)
from relay.tiers import RelayConfig


def run_relay_reference(config: RelayConfig, seed: int, codec_positional: bool = True) -> dict[str, Any]:
    ep = Episode(config.base, seed)
    agent = MemoReferenceAgent(config, seed, codec_positional=codec_positional)
    while not ep.done:
        action, _memo = agent.relay_act(ep.observation())
        err = ep.validate(action)
        if err:
            raise RuntimeError(f"memo reference produced illegal action: {err}")
        ep.apply(action)
    result = dict(ep.result or {})
    result["records"] = ep.records
    result.update(diagnose(ep))
    result["budget_chars"] = config.budget_chars
    result["needed_chars"] = agent.needed_chars
    result["needed_chars_max"] = max(agent.needed_chars, default=0)
    return result


def run_relay_svg(
    adapter,  # VisionAdapter
    config: RelayConfig,
    seed: int,
    transcript_dir: Path | None = None,
    max_retries_per_turn: int = 1,
) -> dict[str, Any]:
    """Pixel-channel episode: the baton is a rendered image of the SVG the
    predecessor wrote. Only pixels cross the gap."""
    from relay.svg_channel import png_b64, render_svg, sanitize_svg

    ep = Episode(config.base, seed)
    usage_before = dict(adapter.usage_totals)
    calls_before = adapter.calls
    system = relay_system_prompt(config)
    image: str | None = None
    turns_log: list[dict[str, Any]] = []
    svg_stats = {"missing": 0, "rejected": 0, "render_failed": 0, "ok": 0}
    total_retries = 0
    if transcript_dir is not None:
        transcript_dir.mkdir(parents=True, exist_ok=True)
    while not ep.done:
        obs = ep.observation()
        header = (
            "YOUR NOTE FROM LAST TURN is the attached image (you drew it)."
            if image is not None
            else "YOUR NOTE FROM LAST TURN: (none — no readable image survived)"
        )
        body = relay_turn_message(obs, config, "", False).split("\n", 1)[1]
        body = body.replace('Include your note for next turn: "note"', 'Include your "svg" note')
        turn_msg = header + "\n" + body
        messages = [Message("system", system), Message("user", turn_msg)]
        reply, meta = adapter.call_with_image(messages, image)
        turn_entry = {"turn": obs.turn, "phase": obs.phase, "had_image": image is not None,
                      "replies": [{"text": reply, **meta}]}
        action, err = parse_action(reply, ep.board)
        if err is None and action is not None:
            err = ep.validate(action)
        retries = 0
        while err is not None and retries < max_retries_per_turn:
            retries += 1
            total_retries += 1
            messages.append(Message("assistant", reply))
            messages.append(Message("user", f"INVALID ACTION: {err} Reply with ONLY a corrected action JSON (including your svg)."))
            reply, meta = adapter.call_with_image(messages, image)
            turn_entry["replies"].append({"text": reply, **meta})
            action, err = parse_action(reply, ep.board)
            if err is None and action is not None:
                err = ep.validate(action)
        data = extract_json(reply)
        svg_src = data.get("svg") if isinstance(data, dict) else None
        image = None
        if not isinstance(svg_src, str) or not svg_src.strip():
            svg_stats["missing"] += 1
        else:
            clean = sanitize_svg(svg_src)
            if clean is None:
                svg_stats["rejected"] += 1
            else:
                png = render_svg(clean)
                if png is None:
                    svg_stats["render_failed"] += 1
                else:
                    svg_stats["ok"] += 1
                    image = png_b64(png)
                    if transcript_dir is not None:
                        (transcript_dir / f"seed{seed:04d}_t{obs.turn:02d}.svg").write_text(clean)
                        (transcript_dir / f"seed{seed:04d}_t{obs.turn:02d}.png").write_bytes(png)
        turns_log.append(turn_entry)
        if err is not None:
            if ep.phase == "guess":
                ep.force_zero_guess(err)
            else:
                ep.skip_turn(err)
            continue
        assert action is not None
        ep.apply(action, meta={"retries": retries})
    result = dict(ep.result or {})
    result["records"] = ep.records
    result.update(diagnose(ep))
    from relay.svg_channel import active_renderer

    result["model"] = adapter.model
    result["effort"] = adapter.effort
    result["condition"] = "svg"
    result["prompt_version"] = prompt_version_for(config.prompt_variant)
    result["renderer"] = active_renderer()
    result["svg_stats"] = svg_stats
    result["total_retries"] = total_retries
    result["api_calls"] = adapter.calls - calls_before
    result["usage"] = {
        k: adapter.usage_totals.get(k, 0) - usage_before.get(k, 0)
        for k in adapter.usage_totals
    }
    if transcript_dir is not None:
        (transcript_dir / f"seed{seed:04d}.json").write_text(
            json.dumps(
                {"result": {k: v for k, v in result.items() if k != "records"},
                 "records": result["records"], "turns": turns_log},
                ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
    return result


def run_relay_llm(
    adapter: APIAdapter,
    config: RelayConfig,
    seed: int,
    transcript_dir: Path | None = None,
    max_retries_per_turn: int = 1,
) -> dict[str, Any]:
    ep = Episode(config.base, seed)
    usage_before = dict(adapter.usage_totals)
    calls_before = adapter.calls
    constitution = None
    if config.condition == "constitution":
        pregame = [
            Message("system", relay_system_prompt(config)),
            Message("user", CONSTITUTION_PROMPT.format(budget=config.budget_chars)),
        ]
        constitution, _ = adapter.call_with_meta(pregame)
        constitution = constitution.strip()[:400]
    system = relay_system_prompt(config, constitution=constitution)
    baton = ""
    truncated = False
    form_invalid_total = 0
    form_overflow_total = 0
    batons: list[dict[str, Any]] = []
    turns_log: list[dict[str, Any]] = []
    total_retries = 0
    while not ep.done:
        obs = ep.observation()
        budget = config.budget_for_turn(obs.turn)
        turn_msg = relay_turn_message(obs, config, baton, truncated)
        messages = [Message("system", system), Message("user", turn_msg)]
        reply, meta = adapter.call_with_meta(messages)
        turn_entry = {
            "turn": obs.turn,
            "phase": obs.phase,
            "baton_in": baton,
            "user": turn_msg,
            "replies": [{"text": reply, **meta}],
        }
        action, err = parse_action(reply, ep.board)
        if err is None and action is not None:
            err = ep.validate(action)
        retries = 0
        while err is not None and retries < max_retries_per_turn:
            retries += 1
            total_retries += 1
            messages.append(Message("assistant", reply))
            messages.append(Message("user", f"INVALID ACTION: {err} Reply with ONLY a corrected action JSON (including your note)."))
            reply, meta = adapter.call_with_meta(messages)
            turn_entry["replies"].append({"text": reply, **meta})
            action, err = parse_action(reply, ep.board)
            if err is None and action is not None:
                err = ep.validate(action)
        # Extract the memory payload from the final reply's JSON.
        data = extract_json(reply)
        if config.condition == "form":
            mem = data.get("mem") if isinstance(data, dict) else None
            baton, invalid, overflow = render_mem(mem, ep.board, budget)
            form_invalid_total += invalid
            form_overflow_total += overflow
            note = baton
            truncated = False
        else:
            note = ""
            if isinstance(data, dict) and isinstance(data.get("note"), str):
                note = data["note"]
            truncated = len(note) > budget
            baton = note[:budget]
        batons.append({"turn": obs.turn, "note_len": len(note), "kept_len": len(baton), "truncated": truncated, "baton": baton})
        turn_entry["baton_out"] = baton
        turns_log.append(turn_entry)
        if err is not None:
            if ep.phase == "guess":
                ep.force_zero_guess(err)
            else:
                ep.skip_turn(err)
            continue
        assert action is not None
        ep.apply(action, meta={"retries": retries})
    result = dict(ep.result or {})
    result["records"] = ep.records
    result.update(diagnose(ep))
    result["model"] = adapter.model
    result["effort"] = adapter.effort
    result["condition"] = config.condition
    result["prompt_version"] = prompt_version_for(config.prompt_variant)
    result["constitution"] = constitution
    # Back-compat total plus the split (validation loss vs capacity loss).
    result["form_dropped_entries"] = form_invalid_total + form_overflow_total
    result["form_invalid_entries"] = form_invalid_total
    result["form_overflow_entries"] = form_overflow_total
    result["budget_chars"] = config.budget_chars if not config.budget_schedule else None
    result["budget_schedule"] = list(config.budget_schedule) if config.budget_schedule else None
    result["batons"] = batons
    result["no_note_turns"] = sum(1 for b in batons if b["note_len"] == 0)
    result["truncated_turns"] = sum(1 for b in batons if b["truncated"])
    result["total_retries"] = total_retries
    result["api_calls"] = adapter.calls - calls_before
    result["usage"] = {
        k: adapter.usage_totals.get(k, 0) - usage_before.get(k, 0)
        for k in adapter.usage_totals
    }
    if transcript_dir is not None:
        transcript_dir.mkdir(parents=True, exist_ok=True)
        (transcript_dir / f"seed{seed:04d}.json").write_text(
            json.dumps(
                {
                    "result": {k: v for k, v in result.items() if k not in ("records",)},
                    "records": result["records"],
                    "turns": turns_log,
                },
                ensure_ascii=False,
                indent=1,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    return result
