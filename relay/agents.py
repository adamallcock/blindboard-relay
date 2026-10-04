"""MemoReferenceAgent: the budget-matched certificate for the relay track.

A sound player whose belief state is carried in a B-character note:
each turn it deserializes the note into a fresh tracker,
ingests the current observation, acts, then serializes the tracker back
through the budget (densest facts first; overflow torn off). Its
accuracy-vs-budget curve records an attainable policy, not an optimal
capacity bound. The policy's seeded RNG persists between turns; current
observations and environment feedback also remain available. Serialization
lengths describe this policy's evaluated trajectories."""

from __future__ import annotations

from blindboard.agents import ReferenceAgent
from blindboard.env import Action, Observation
from relay.codec import deserialize, serialize, serialize_budgeted, serialize_entries
from relay.tiers import RelayConfig


class MemoReferenceAgent(ReferenceAgent):
    def __init__(
        self,
        relay_config: RelayConfig,
        seed: int,
        samples: int = 30,
        codec_positional: bool = True,
    ) -> None:
        super().__init__(relay_config.base, seed, samples=samples)
        self.relay_config = relay_config
        self.codec_positional = codec_positional  # False = codec v1 (entries only)
        self.needed_chars: list[int] = []
        self.memo = ""

    def relay_act(self, obs: Observation) -> tuple[Action, str]:
        """One amnesiac turn: baton -> tracker -> act -> baton'."""
        self.tracker = deserialize(self.memo, self.board)
        # Re-locking already-locked keys is harmless (env ignores dupes),
        # so the locked-set need not survive the channel.
        self.locked = set()
        action = self.act(obs)  # ingests obs, chooses chord/locks/guess
        # needed_chars must reflect the codec generation actually in use:
        # under v1 (entries-only) the shortest-of-both v2 serializer would
        # under-report the channel demand.
        full = (serialize(self.tracker) if self.codec_positional
                else serialize_entries(self.tracker))
        self.needed_chars.append(len(full))
        budget = self.relay_config.budget_for_turn(obs.turn)
        self.memo = serialize_budgeted(self.tracker, budget, positional=self.codec_positional)
        return action, self.memo
