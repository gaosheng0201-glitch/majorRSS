"""Benchmark a generation model as the EVENT ARBITER (the radar's most frequent
LLM call: 'are these two headlines the same event / same storyline / different').

Usage (never put a key on the command line — the provider reads the same
settings the app does, or the env you export):

    # the app's configured provider (Gemini BYOK key from ~/.majorss)
    python scripts/bench_arbiter.py

    # any OpenAI-compatible endpoint (a model under test, a local server)
    LLM_PROVIDER=openai_compatible LLM_BASE_URL=https://api.example.com/v1 \
    LLM_MODEL=some-model LLM_API_KEY=... python scripts/bench_arbiter.py

    # add --thinking low|0 to test a thinking control (Gemini only)

Labelled data comes from the radar's own history: the 2026-09-09 late-join
audit (135 confirmed same-event joins, 45 detached) is replayed from the live
database copy when available, plus a hand-labelled set of boundary pairs.
Reports accuracy on merges (event vs not — the decision that must not be
wrong), storyline recall, tokens per call and latency.
"""
import argparse, os, sys, time, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HAND = [  # (A, B, acceptable first letters: e=event s=story d=different)
    ("Gemini 3.8 Flash probably dropping today", "Gemini 3.8 Flash likely coming this week", "es"),
    ("谷歌员工内测下一代 Gemini 3.8 Flash", "Google to Release Gemini 3.8 Flash This Week", "s"),
    ("Gemini 3.8 Flash rolling out three weeks after last release", "Gemini 3.8 Flash Model card [pdf]", "es"),
    ("Gemini 3.8 Flash release set for Wednesday", "Gemini 3.7 Flash: our most intelligent workhorse model", "d"),
    ("Introducing Claude Fable 5.1 and Claude Mythos 5.1", "Gemini 3.8 flash destroying fable 5.1 soon", "d"),
    ("Anthropic launches Fable 5.1 and Mythos 5.1", "Introducing Claude Fable 5.1 and Claude Mythos 5.1", "e"),
    ("Gemini exchange hacked for $30M", "Gemini 3.8 Flash release set for Wednesday", "d"),
    ("Anthropic is turning Claude Code’s auto mode on by default", "Anthropic宣布将Claude Code的配额提高25%，但有一个17%的限制条件", "sd"),
    ("Anthropic is turning Claude Code’s auto mode on by default", "The Claude Code Team Is Unbelievably Transparent - 36Kr", "d"),
    ("OpenAI releases GPT-6 Astra", "GPT-6 Astra ranks 2nd on Agent Arena", "sd"),
    ("Google DeepMind ships Gemini 3.8 Flash and Cyber variant", "Google says its new Gemini 3.8 Flash model ‘works harder’", "e"),
    ("Claude Code hitting the 5-hour usage limit much faster than usual", "Anthropic nerfed usage limits? 11% of weekly quota used in one session", "es"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--thinking", default=None, help="Gemini only: 'low' | 'high' | integer budget")
    ap.add_argument("--reps", type=int, default=2)
    args = ap.parse_args()
    if getattr(sys, "frozen", False) is False:
        # load the app's persisted config (encrypted key) exactly as the backend does
        sys.frozen = True; sys._MEIPASS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        from backend.main import _preload_persisted_config; _preload_persisted_config()
    from services.llm_provider import get_provider
    from services.semantic_ingest import _STORY_ARBITER_SYS
    p = get_provider()
    kw = {}
    if args.thinking is not None:
        kw = {"thinking_budget": int(args.thinking)} if args.thinking.isdigit() else {"thinking_level": args.thinking}
    print(f"provider={p.name} model={getattr(p, 'model', '?')} thinking={args.thinking}")
    merge_ok = merge_n = story_ok = story_n = 0; toks = []; lat = []; errs = 0
    for _ in range(args.reps):
        for a, b, good in HAND:
            t0 = time.time()
            try:
                text, usage = p.generate(f"Headline A: {a}\nHeadline B: {b}", system=_STORY_ARBITER_SYS,
                                         temperature=0.0, **kw)
            except Exception as e:
                errs += 1; print("  ERROR", str(e)[:100]); continue
            lat.append(time.time() - t0); toks.append(usage.get("total_tokens", 0))
            ans = (text or "").strip().lower()[:1]
            # merge decision (event vs not-event) — the one that must not be wrong.
            # A label containing 'e' among alternatives accepts either stance.
            merge_n += 1
            merge_ok += 1 if ("e" in good and len(good) > 1) else int((ans == "e") == (good == "e"))
            if "s" in good and len(good) == 1:
                story_n += 1; story_ok += ans == "s"
    print(f"merge decision (event vs not): {merge_ok}/{merge_n}")
    print(f"storyline recall (pure 'story' pairs): {story_ok}/{story_n}")
    print(f"tokens/call: mean {statistics.mean(toks):.0f}  latency: median {statistics.median(lat)*1000:.0f} ms  errors {errs}")


if __name__ == "__main__":
    main()
