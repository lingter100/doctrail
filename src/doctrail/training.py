"""Small explicit-negative training primitives; importing this module needs no Torch."""

from __future__ import annotations

import math
import random


class UpdateProgress:
    """Shared execution evidence that survives exceptions, independent of Torch.

    An optimizer call may partially mutate weights before raising. Completed calls
    and independently verified weight changes are therefore separate counters.
    The optional sink persists each event before the next operation begins.
    """

    def __init__(self, state: dict, sink=None):
        self.state = state
        self.sink = sink
        state.update({"optimizer_groups_started": 0, "optimizer_steps_attempted": 0,
                      "optimizer_step_calls": 0, "optimizer_steps_completed": 0,
                      "optimizer_steps_verified": 0, "optimizer_steps": 0,
                      "weight_updates_observed": 0, "weight_update_status": "not_observed",
                      "current_optimizer_weight_update_status": "not_observed",
                      "steps": [], "events": []})

    def emit(self, event: str, **details) -> None:
        row = {"sequence": len(self.state["events"]) + 1, "event": event, **details}
        self.state["events"].append(row)
        if self.sink is not None:
            self.sink(row)

    def attempt(self, step: int) -> None:
        self.state["optimizer_steps_attempted"] += 1
        self.emit("scaled_optimizer_step_attempted", optimizer_step=step)

    def entered(self) -> None:
        self.state["optimizer_step_calls"] += 1
        self.state["current_optimizer_weight_update_status"] = "unknown_until_verified"
        if not self.state["weight_updates_observed"]:
            self.state["weight_update_status"] = "unknown_until_verified"
        self.emit("optimizer_step_entered", call=self.state["optimizer_step_calls"])

    def completed(self) -> None:
        self.state["optimizer_steps_completed"] += 1
        self.state["optimizer_steps"] = self.state["optimizer_steps_completed"]
        self.emit("optimizer_step_returned", completed=self.state["optimizer_steps_completed"])

    def observed(self, step: dict, changed: bool) -> None:
        # This may run after an optimizer exception to preserve a partial mutation.
        if changed and not step.get("weight_change_observed", False):
            self.state["weight_updates_observed"] += 1
        step["weight_change_observed"] = step.get("weight_change_observed", False) or changed
        self.state["current_optimizer_weight_update_status"] = "observed" if changed else "not_observed"
        self.state["weight_update_status"] = (
            "observed" if self.state["weight_updates_observed"] else "not_observed")
        self.emit("weight_witness_observed", optimizer_step=step["optimizer_step"], changed=changed)

    def execution_flags(self, command: str) -> dict:
        entered = self.state["optimizer_step_calls"] > 0
        return {"training_attempted": command == "train" and
                self.state["optimizer_groups_started"] > 0,
                "training_executed": command == "train" and entered,
                "probe_optimizer_executed": command == "probe" and entered,
                "probe_weight_update_executed": command == "probe" and
                self.state["weight_updates_observed"] > 0}


def optimizer_batches(records: list[dict], *, seed: int, epochs: int,
                      microbatch: int, accumulation: int, max_steps: int):
    """Yield complete optimizer groups, never silently discard a partial batch."""
    if not records or min(epochs, microbatch, accumulation, max_steps) < 1:
        raise ValueError("invalid_training_schedule")
    if len({row["question_id"] for row in records}) != len(records):
        raise ValueError("duplicate_training_question")
    base = sorted(records, key=lambda row: row["question_id"])
    steps = 0
    for epoch in range(epochs):
        order = base.copy()
        random.Random(seed + epoch).shuffle(order)
        width = microbatch * accumulation
        for start in range(0, len(order), width):
            if steps >= max_steps:
                return
            group = order[start:start + width]
            yield {"epoch": epoch + 1, "optimizer_step": steps + 1,
                   "question_count": len(group),
                   "microbatches": [group[i:i + microbatch]
                                    for i in range(0, len(group), microbatch)]}
            steps += 1


def per_query_contrastive_loss(queries, passages, temperature: float = 0.01):
    """Each query has its own positive at index0 and exactly two explicit negatives."""
    import torch
    from torch.nn import functional

    if (queries.ndim != 2 or passages.ndim != 3
            or tuple(passages.shape) != (queries.shape[0], 3, queries.shape[1])
            or queries.shape[0] == 0):
        raise ValueError("invalid_explicit_negative_dimensions")
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("invalid_temperature")
    if not torch.isfinite(queries).all() or not torch.isfinite(passages).all():
        raise ValueError("nonfinite_training_embeddings")
    if torch.any(queries.norm(dim=-1) <= 0) or torch.any(passages.norm(dim=-1) <= 0):
        raise ValueError("zero_training_embedding")
    q = functional.normalize(queries.float(), p=2, dim=-1)
    p = functional.normalize(passages.float(), p=2, dim=-1)
    logits = torch.einsum("bd,bkd->bk", q, p) / temperature
    labels = torch.zeros(queries.shape[0], dtype=torch.long, device=queries.device)
    return functional.cross_entropy(logits, labels)


def constant_learning_rate(step: int, total_steps: int, warmup_steps: int, peak: float) -> float:
    """One-based linear warmup, then constant LR; no unregistered decay schedule."""
    if (not 1 <= step <= total_steps or not 0 <= warmup_steps < total_steps
            or not math.isfinite(peak) or peak <= 0):
        raise ValueError("invalid_learning_rate_schedule")
    if warmup_steps and step <= warmup_steps:
        return peak * step / warmup_steps
    return peak
