"""Simple LLM cost tracking."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CostTracker:
    """Track prompt/completion tokens and estimate USD cost.

    Uses approximate per-model pricing (per 1M tokens).
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0.0

    # (input_rate, output_rate) per 1M tokens in USD
    _MODEL_RATES: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "claude-sonnet-4": (3.0, 15.0),
            "claude-opus-4": (15.0, 75.0),
            "claude-haiku-4": (0.80, 4.0),
            "gpt-4o": (2.50, 10.0),
            "gpt-4.1": (2.0, 8.0),
            "default": (1.0, 5.0),
        }
    )

    def track(self, prompt_tokens: int, completion_tokens: int, model: str = "default") -> None:
        """Record a usage sample and update running totals."""
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        rate = self._best_rate(model)
        self.total_cost_usd += (
            (prompt_tokens / 1_000_000) * rate[0]
            + (completion_tokens / 1_000_000) * rate[1]
        )

    def _best_rate(self, model: str) -> tuple[float, float]:
        """Find the closest matching rate for *model*."""
        for key, rate in self._MODEL_RATES.items():
            if key in model.lower():
                return rate
        return self._MODEL_RATES["default"]
