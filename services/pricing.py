"""Model pricing table for cost estimation (USD per 1,000,000 tokens).

IMPORTANT: these numbers are **best-effort placeholders — verify and update them
against current official pricing**. What matters structurally (the actual fix):
input and output are priced SEPARATELY (output is typically several× input), and
embedding models are included (output price 0). Matched by substring so varying
model-name strings ("gemini", "gemini-3.6-flash", …) all resolve.
"""
from typing import Tuple

# (name_substring, input_usd_per_1m, output_usd_per_1m). First match wins, so
# order most-specific → least-specific.
_PRICES = [
    ("gemini-3.6-flash", 0.30, 2.50),
    ("gemini-3.5-flash", 0.30, 2.50),
    ("gemini-3.1-pro",   1.25, 10.0),
    ("gemini-3-pro",     1.25, 10.0),
    ("gemini-2.5-flash", 0.15, 0.60),
    ("gemini-2.5-pro",   1.25, 10.0),
    ("gemini-2.0-flash", 0.10, 0.40),
    ("gemini-embedding", 0.15, 0.0),
    ("text-embedding",   0.02, 0.0),
    ("gpt-4o-mini",      0.15, 0.60),
    ("gpt-4o",           2.50, 10.0),
    ("embedding",        0.02, 0.0),   # generic embedding fallback
    ("flash",            0.30, 2.50),  # generic flash fallback
    ("pro",              1.25, 10.0),  # generic pro fallback
    ("gemini",           0.30, 2.50),  # generic gemini (legacy "gemini" records)
]
_DEFAULT: Tuple[float, float] = (0.30, 2.50)


def price_for(model_name: str) -> Tuple[float, float]:
    m = (model_name or "").lower()
    for sub, inp, out in _PRICES:
        if sub in m:
            return inp, out
    return _DEFAULT


def cost_usd(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    inp, out = price_for(model_name)
    return (prompt_tokens / 1_000_000.0) * inp + (completion_tokens / 1_000_000.0) * out
