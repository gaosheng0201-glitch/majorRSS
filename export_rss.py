import sys
import os
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

# Ensure root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.database import get_session
from db.models import IntelReport
from sqlmodel import select
import markdown

def generate_feed():
    session = next(get_session())
    reports = session.exec(
        select(IntelReport)
        .where(IntelReport.validity_category.in_(["[VALID_NEWS]", "VALID_NEWS"]))
        .order_by(IntelReport.created_at.desc())
        .limit(50)
    ).all()

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    
    ET.SubElement(channel, "title").text = "MajorRSS Global Intel"
    ET.SubElement(channel, "link").text = "https://github.com/majorrss"
    ET.SubElement(channel, "description").text = "Decentralized AI Fact-Checked Information Radar"
    
    for r in reports:
        item = ET.SubElement(channel, "item")
        title_text = f"[{r.importance_score}⭐] {r.source_url.split('/')[-1] if '/' in r.source_url else r.source_url}"
        ET.SubElement(item, "title").text = title_text
        ET.SubElement(item, "link").text = r.source_url
        
        # Convert markdown summary to HTML for RSS readers
        html_summary = markdown.markdown(r.llm_summary)
        ET.SubElement(item, "description").text = html_summary
        
        ET.SubElement(item, "category").text = r.radar_section
        ET.SubElement(item, "pubDate").text = r.created_at.strftime("%a, %d %b %Y %H:%M:%S +0000")
        ET.SubElement(item, "guid").text = r.original_content_hash

    # Save to file
    feed_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed.xml")
    tree = ET.ElementTree(rss)
    # Using xml declaration and utf-8
    with open(feed_path, 'wb') as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="utf-8")
        
    print(f"Generated human-readable RSS feed at {feed_path}")

if __name__ == "__main__":
    generate_feed()
