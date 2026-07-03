from fastapi import APIRouter, HTTPException

from services.source_preset_service import (
    list_source_preset_collections,
    list_source_presets,
    upsert_source_presets_from_seed,
)

router = APIRouter(prefix="/source-presets", tags=["source-presets"])


@router.get("/collections")
def get_source_preset_collections():
    return list_source_preset_collections()


@router.get("/sources")
def get_source_presets(collection_id: str | None = None):
    return list_source_presets(collection_id=collection_id)


@router.post("/seed")
def seed_source_presets():
    try:
        return upsert_source_presets_from_seed()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
