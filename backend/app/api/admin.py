from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.rag.ingest import ingestion_pipeline

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
