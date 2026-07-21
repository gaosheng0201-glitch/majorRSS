"""Publish exporter compliance gate — the safety-critical R7 path."""
from datetime import datetime, timezone, timedelta

from services.privacy import clean_pii
from services import publish_service as pub


def _seed_thread(title, sources, lifecycle="CONFIRMED", is_resonant=False):
    """Create a StoryThread + its member RawArticles; return thread id."""
    from db.database import get_session
    from db.models import Tracker, StoryThread, RawArticle
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_session() as s:
        tr = Tracker(name="T", tracker_type="KEYWORD", target="[]",
                     source_intent="KEYWORD_DISCOVERY", radar_section="R", is_active=True)
        s.add(tr); s.commit(); s.refresh(tr)
        th = StoryThread(tracker_id=tr.id, title=title, lifecycle=lifecycle,
                         distinct_source_count=len(sources), member_count=len(sources),
                         is_resonant=is_resonant, first_seen_at=now, last_update_at=now)
        s.add(th); s.commit(); s.refresh(th)
        for t, url in sources:
            s.add(RawArticle(tracker_id=tr.id, title=t, url=url, content="x",
                             thread_id=th.id, published_at=now, created_at=now))
        s.commit()
        return th.id


def test_clean_pii_redacts():
    out = clean_pii("联系 a@b.com 或 13800138000，坐标 39.904200,116.407396")
    assert "a@b.com" not in out and "[email]" in out
    assert "13800138000" not in out and "[phone]" in out
    assert "39.904200,116.407396" not in out and "[location]" in out


def test_auth_content_excluded():
    """A thread with a source on an authorized-platform domain must never be
    published (auth content never leaves the machine)."""
    _seed_thread("public event only", [("A", "https://openai.com/x"), ("B", "https://reuters.com/y")])
    _seed_thread("has twitter source", [("C", "https://x.com/someone/status/1"), ("D", "https://openai.com/z")])
    d = pub.build_published_digest(window_hours=1)
    titles = [t["title"] for t in d["threads"]]
    assert "public event only" in titles
    assert "has twitter source" not in titles  # excluded by the auth gate


def test_summary_capped_and_pii_cleaned():
    long_title = "泄露 test@leak.com " + ("很长的标题内容 " * 60)
    _seed_thread(long_title, [("S", "https://blog.example.com/a")], lifecycle="LEAD")
    d = pub.build_published_digest(window_hours=1)
    th = next(t for t in d["threads"] if t["title"].startswith("泄露"))
    assert "test@leak.com" not in th["summary"]["text"]      # PII cleaned
    assert len(th["summary"]["text"]) <= pub.PUBLIC_SUMMARY_MAX_CHARS


def test_fact_level_and_source_kind():
    _seed_thread("confirmed w/ github", [("repo", "https://github.com/a/b"),
                                          ("media", "https://techsite.example.com/x")])
    d = pub.build_published_digest(window_hours=1)
    th = next(t for t in d["threads"] if t["title"] == "confirmed w/ github")
    assert th["fact_level"] == "verified"                    # CONFIRMED -> verified
    assert th["sources"][0]["kind"] == "first_party"         # github sorted first
    assert th["provenance"]["auth_content_excluded"] is True
    assert th["provenance"]["pii_cleaned"] is True


def test_contract_shape():
    _seed_thread("shape check", [("s", "https://openai.com/p")])
    d = pub.build_published_digest(window_hours=1)
    assert d["contract_version"] == "0.1"
    assert d["publisher"]["signature"] is None               # phase 1
    assert isinstance(d["threads"], list) and isinstance(d["topics"], list)
    th = next(t for t in d["threads"] if t["title"] == "shape check")
    assert th["id"].startswith("thr_")                       # hashed, not raw int
    for s in th["sources"]:
        assert s["url"] and s["published_at"] is not None    # provenance three-piece
