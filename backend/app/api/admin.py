from collections import Counter

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query

from app.rag.ingest import ingestion_pipeline
from app.rag.vector_store import vector_store
from app.rag.chunker import _detect_content_type

router = APIRouter()


@router.post("/admin/ingest")
async def ingest_pdf(
    file: UploadFile = File(...),
    vehicle_id: str = Form(...),
    make: str = Form(""),
    model: str = Form(""),
    year: int = Form(0),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF file required")
    try:
        content = await file.read()
        result = await ingestion_pipeline.ingest(
            pdf_bytes=content,
            filename=file.filename,
            vehicle_id=vehicle_id,
            make=make,
            model=model,
            year=year,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion error: {str(e)}")


@router.get("/admin/content-type-stats")
async def content_type_stats(vehicle_id: str = Query(...)):
    """Show content_type distribution and diff against re-classification (max 50 diffs)."""
    try:
        collection = vector_store._get_collection()
        results = collection.get(
            where={"vehicle_id": vehicle_id},
            include=["documents", "metadatas"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")

    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []

    # Current distribution
    current_counts: Counter = Counter()
    diffs: list[dict] = []

    for doc, meta in zip(documents, metadatas):
        stored_type = meta.get("content_type", "general")
        current_counts[stored_type] += 1

        reclassified = _detect_content_type(doc)
        if reclassified != stored_type and len(diffs) < 50:
            diffs.append({
                "page": meta.get("page", 0),
                "section": meta.get("section", ""),
                "stored": stored_type,
                "reclassified": reclassified,
                "text_preview": doc[:120] if doc else "",
            })

    return {
        "vehicle_id": vehicle_id,
        "total_chunks": len(documents),
        "distribution": dict(current_counts),
        "reclassification_diffs": diffs,
        "diff_count": len(diffs),
    }


@router.get("/admin/content-type-samples")
async def content_type_samples(
    vehicle_id: str = Query(...),
    content_type: str = Query(...),
    limit: int = Query(20, ge=1, le=100),
):
    """Show sample chunks for a specific content_type."""
    try:
        collection = vector_store._get_collection()
        results = collection.get(
            where={"$and": [
                {"vehicle_id": vehicle_id},
                {"content_type": content_type},
            ]},
            include=["documents", "metadatas"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")

    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []

    samples = []
    for doc, meta in zip(documents[:limit], metadatas[:limit]):
        samples.append({
            "page": meta.get("page", 0),
            "section": meta.get("section", ""),
            "has_warning": meta.get("has_warning", False),
            "text_preview": doc[:200] if doc else "",
        })

    return {
        "vehicle_id": vehicle_id,
        "content_type": content_type,
        "total": len(documents),
        "showing": len(samples),
        "samples": samples,
    }
