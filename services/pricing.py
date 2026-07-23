"""Model pricing table for cost estimation (USD per 1,000,000 tokens).

Gemini prices from the official pricing page (paid tier, standard), verified
2026-07-23: https://ai.google.dev/gemini-api/docs/pricing — update here when
Google changes them. Input and output are priced SEPARATELY (output costs
several× input), and embedding models are included (output 0). Matched by
substring so varying model-name strings ("gemini", "gemini-3.6-flash", …)
resolve; first match wins, so order most-specific → least-specific.
"""
from typing import Tuple

# (name_substring, input_usd_per_1m, output_usd_per_1m).
_PRICES = [
    ("gemini-embedding-2", 0.20, 0.0),   # embedding-2 text input
    ("gemini-embedding",   0.15, 0.0),   # gemini-embedding-001
    ("text-embedding",     0.15, 0.0),
    ("gemini-3.6-flash",   1.50, 7.50),
    ("gemini-3.5-flash",   1.50, 9.00),
    ("gemini-3.1-pro",     1.25, 10.0),  # not separately listed; 2.5-pro proxy
    ("gemini-3-pro",       1.25, 10.0),  # proxy
    ("gemini-2.5-flash",   0.30, 2.50),
    ("gemini-2.5-pro",     1.25, 10.0),  # ≤200k tier
    ("gemini-2.0-flash",   0.10, 0.40),
    ("gpt-4o-mini",        0.15, 0.60),
    ("gpt-4o",             2.50, 10.0),
    ("embedding",          0.15, 0.0),   # generic embedding fallback
    ("flash",              1.50, 7.50),  # generic flash fallback (current gen)
    ("pro",                1.25, 10.0),  # generic pro fallback
    ("gemini",             1.50, 7.50),  # legacy "gemini" records ≈ default flash
]
_DEFAULT: Tuple[float, float] = (1.50, 7.50)


def price_for(model_name: str) -> Tuple[float, float]:
    m = (model_name or "").lower()
    for sub, inp, out in _PRICES:
        if sub in m:
            return inp, out
    return _DEFAULT


def cost_usd(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    inp, out = price_for(model_name)
    return (prompt_tokens / 1_000_000.0) * inp + (completion_tokens / 1_000_000.0) * out
