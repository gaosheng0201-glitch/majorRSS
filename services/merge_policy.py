"""合并策略 — ONE declaration of when two things are judged the same event.

Two stages, one judge (semantic_ingest._llm_relation), one place for the
numbers. Intake is conservative: a wrong merge poisons a summary and dresses
an old story as news, and cannot be undone; a split can. So intake only asks
about the K nearest threads and never merges on embedding alone below the
confident line. The post-hoc pass completes the recoverable direction: pairs
of recent threads above POSTHOC_MIN_SIMILARITY are asked pair by pair, so no
candidate cap can hide a neighbour (measured 2026-09-22: the Opus 5.5 launch
thread sat fourth behind three Fable-launch threads and was never asked).

Calibration notes (revise with data, record here):
  - INGEST_CANDIDATE_FLOOR 0.05: centred space; same-event pairs incl. cross-
    language sit at 0.54-0.58, unrelated near 0 (2026-07-29 measurement).
  - INGEST_HIGH_CONFIDENCE 0.80: above this, near-identical; merged unjudged.
  - INGEST_CANDIDATES 3: top-1 was a measured failure (80% splits); 3 keeps
    typical batches under the per-cycle call cap.
  - POSTHOC_MIN_SIMILARITY 0.70: first live pass judged 20 pairs, merged 2
    (both true duplicates), rejected 18 sensibly — no false merge at 0.70.
  - POSTHOC_WINDOW_HOURS 48 / MAX_PAIRS 20: bounds spend; splits older than
    two days are rare and cheap to leave.
"""
INGEST_CANDIDATE_FLOOR = 0.05
INGEST_HIGH_CONFIDENCE = 0.80
INGEST_CANDIDATES = 3
INGEST_CALLS_PER_CYCLE = 300
POOL_WINDOW_DAYS = 30

POSTHOC_MIN_SIMILARITY = 0.70
POSTHOC_WINDOW_HOURS = 48
POSTHOC_MAX_PAIRS = 20
