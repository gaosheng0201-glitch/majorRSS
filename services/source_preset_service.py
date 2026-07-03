import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlmodel import select

from db.database import get_session
from db.models import SourcePreset, SourcePresetCollection, SourcePresetCollectionItem


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_source_preset_seed_path() -> Optional[str]:
    candidates = []

    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(getattr(sys, "_MEIPASS", ""), "docs", "source_presets.seed.json"))
        candidates.append(os.path.join(os.path.dirname(sys.executable), "docs", "source_presets.seed.json"))

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(root_dir, "docs", "source_presets.seed.json"))
    candidates.append(os.path.join(os.getcwd(), "docs", "source_presets.seed.json"))

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def load_source_preset_seed(path: Optional[str] = None) -> Dict[str, Any]:
    seed_path = path or get_source_preset_seed_path()
    if not seed_path:
        raise FileNotFoundError("source_presets.seed.json was not found")

    with open(seed_path, "r", encoding="utf-8") as f:
        return json.load(f)


def upsert_source_presets_from_seed(path: Optional[str] = None) -> Dict[str, int]:
    seed = load_source_preset_seed(path)
    sources = seed.get("sources", [])
    collections = seed.get("collections", [])
    now = _now()

    with get_session() as session:
        source_upserts = 0
        collection_upserts = 0
        relation_upserts = 0

        for src in sources:
            preset_id = src["id"]
            existing = session.exec(
                select(SourcePreset).where(SourcePreset.preset_id == preset_id)
            ).first()
            if not existing:
                existing = SourcePreset(preset_id=preset_id, title=src.get("title", preset_id), source_type=src.get("source_type", "rss"), url=src.get("url", ""))

            existing.title = src.get("title", preset_id)
            existing.description = src.get("description")
            existing.source_type = src.get("source_type", "rss")
            existing.url = src.get("url", "")
            existing.canonical_site = src.get("canonical_site")
            existing.categories_json = _json_dumps(src.get("category", []))
            existing.tags_json = _json_dumps(src.get("tags", []))
            existing.language = src.get("language")
            existing.region = src.get("region")
            existing.importance = src.get("importance")
            existing.noise_level = src.get("noise_level")
            existing.update_frequency = src.get("update_frequency")
            existing.requires_auth = bool(src.get("requires_auth", False))
            existing.owner_type = src.get("owner_type", "built_in")
            existing.verification_status = src.get("verification_status", "candidate")
            existing.raw_metadata = json.dumps(src, ensure_ascii=False)
            existing.updated_at = now
            session.add(existing)
            source_upserts += 1

        session.commit()

        for col in collections:
            collection_id = col["id"]
            source_ids = col.get("source_ids", [])
            existing = session.exec(
                select(SourcePresetCollection).where(SourcePresetCollection.collection_id == collection_id)
            ).first()
            if not existing:
                existing = SourcePresetCollection(collection_id=collection_id, title=col.get("title", collection_id))

            existing.title = col.get("title", collection_id)
            existing.description = col.get("description")
            existing.categories_json = _json_dumps(col.get("category", []))
            existing.owner_type = col.get("owner_type", "built_in")
            existing.default_keywords_json = _json_dumps(col.get("default_keywords", []))
            existing.default_summary_style = col.get("default_summary_style")
            existing.source_count = len(source_ids)
            existing.updated_at = now
            session.add(existing)
            collection_upserts += 1

            existing_items = session.exec(
                select(SourcePresetCollectionItem).where(SourcePresetCollectionItem.collection_id == collection_id)
            ).all()
            existing_by_source = {item.preset_id: item for item in existing_items}
            desired_ids = set(source_ids)

            for item in existing_items:
                if item.preset_id not in desired_ids:
                    session.delete(item)

            for idx, preset_id in enumerate(source_ids):
                item = existing_by_source.get(preset_id)
                if not item:
                    item = SourcePresetCollectionItem(collection_id=collection_id, preset_id=preset_id)
                item.sort_order = idx
                session.add(item)
                relation_upserts += 1

        session.commit()

    return {
        "sources": source_upserts,
        "collections": collection_upserts,
        "collection_items": relation_upserts,
    }


def list_source_preset_collections() -> list[Dict[str, Any]]:
    with get_session() as session:
        collections = session.exec(select(SourcePresetCollection).order_by(SourcePresetCollection.title)).all()
        result = []
        for col in collections:
            result.append({
                "id": col.id,
                "collection_id": col.collection_id,
                "title": col.title,
                "description": col.description,
                "categories": json.loads(col.categories_json or "[]"),
                "owner_type": col.owner_type,
                "default_keywords": json.loads(col.default_keywords_json or "[]"),
                "default_summary_style": col.default_summary_style,
                "source_count": col.source_count,
                "updated_at": col.updated_at,
            })
        return result


def list_source_presets(collection_id: Optional[str] = None) -> list[Dict[str, Any]]:
    with get_session() as session:
        if collection_id:
            items = session.exec(
                select(SourcePresetCollectionItem)
                .where(SourcePresetCollectionItem.collection_id == collection_id)
                .order_by(SourcePresetCollectionItem.sort_order)
            ).all()
            preset_ids = [item.preset_id for item in items]
            presets_by_id = {
                preset.preset_id: preset
                for preset in session.exec(select(SourcePreset).where(SourcePreset.preset_id.in_(preset_ids))).all()
            }
            presets = [presets_by_id[preset_id] for preset_id in preset_ids if preset_id in presets_by_id]
        else:
            presets = session.exec(select(SourcePreset).order_by(SourcePreset.title)).all()

        result = []
        for preset in presets:
            result.append({
                "id": preset.id,
                "preset_id": preset.preset_id,
                "title": preset.title,
                "description": preset.description,
                "source_type": preset.source_type,
                "url": preset.url,
                "canonical_site": preset.canonical_site,
                "categories": json.loads(preset.categories_json or "[]"),
                "tags": json.loads(preset.tags_json or "[]"),
                "language": preset.language,
                "region": preset.region,
                "importance": preset.importance,
                "noise_level": preset.noise_level,
                "update_frequency": preset.update_frequency,
                "requires_auth": preset.requires_auth,
                "owner_type": preset.owner_type,
                "verification_status": preset.verification_status,
                "updated_at": preset.updated_at,
            })
        return result
