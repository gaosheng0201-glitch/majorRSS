"""
Readability-style main-content extraction (R1).

The old path (strip script/style/nav, then get_text over the whole body) drags
in menus, cookie banners, related-article rails and footer boilerplate — noise
that inflates LLM token cost and pollutes summaries. This scores block elements
by text density (à la the classic Readability algorithm) and returns the main
article text only. Dependency-free: uses lxml, already in the tree, so it adds
nothing to the PyInstaller sidecar. (trafilatura would score marginally higher
but pulls in several transitive deps; revisit only if extraction quality is a
measured bottleneck.)
"""
import re
from typing import Optional

from lxml import html as lxml_html
from lxml.etree import strip_elements

from services.log_service import get_logger

logger = get_logger("extract")

_STRIP_TAGS = ["script", "style", "noscript", "svg", "iframe", "form", "button"]
# Class/id substrings that mark chrome rather than content.
_NEGATIVE = re.compile(
    r"(nav|menu|sidebar|footer|header|comment|share|social|promo|banner|advert|"
    r"cookie|popup|modal|related|recommend|subscribe|newsletter|breadcrumb|pagination|widget)",
    re.I,
)
_POSITIVE = re.compile(r"(article|content|post|entry|main|body|story|text)", re.I)
_BLOCK_TAGS = {"div", "article", "section", "main", "td"}


def _clean_text(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def _node_attr_blob(node) -> str:
    return f"{node.get('class','')} {node.get('id','')}"


def extract_main_text(raw_html: str, min_len: int = 200) -> str:
    """Return the cleaned main-content text of an HTML page.
    Falls back to whole-body text if scoring finds nothing substantial."""
    if not raw_html or not raw_html.strip():
        return ""
    try:
        doc = lxml_html.fromstring(raw_html)
    except Exception as e:
        logger.warning(f"lxml parse failed, returning empty: {e}")
        return ""

    strip_elements(doc, *_STRIP_TAGS, with_tail=False)

    # Structurally drop chrome up front: obvious chrome tags, plus any element
    # whose class/id names it as chrome (nav/footer/sidebar/cookie/…). Doing
    # this before scoring means even the whole-body fallback stays clean when
    # no single block scores high enough (e.g. short pages).
    for tag in ("nav", "header", "footer", "aside"):
        for el in doc.findall(f".//{tag}"):
            el.getparent().remove(el) if el.getparent() is not None else None
    for el in list(doc.iter()):
        blob = _node_attr_blob(el)
        if blob.strip() and _NEGATIVE.search(blob) and not _POSITIVE.search(blob):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    # Score candidate block containers by text length, paragraph count and
    # comma density; penalize chrome-y class/id names, reward article-y ones.
    best_node = None
    best_score = 0.0
    for node in doc.iter():
        if node.tag not in _BLOCK_TAGS:
            continue
        text = node.text_content() or ""
        text_len = len(text.strip())
        if text_len < min_len:
            continue
        paragraphs = len(node.findall(".//p"))
        commas = text.count(",") + text.count("，")
        score = text_len / 100.0 + paragraphs * 3 + commas
        blob = _node_attr_blob(node)
        if _NEGATIVE.search(blob):
            score *= 0.2
        if _POSITIVE.search(blob):
            score *= 1.5
        # Link density penalty: nav-like blocks are mostly anchor text.
        link_text = sum(len(a.text_content() or "") for a in node.findall(".//a"))
        if text_len and link_text / text_len > 0.5:
            score *= 0.3
        if score > best_score:
            best_score = score
            best_node = node

    if best_node is not None:
        return _clean_text(best_node.text_content())

    # Fallback: whole body text (still better than raw HTML).
    body = doc.find(".//body")
    target = body if body is not None else doc
    return _clean_text(target.text_content())
