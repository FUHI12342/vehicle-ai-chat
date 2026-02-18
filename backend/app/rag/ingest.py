from app.rag.pdf_loader import pdf_loader
from app.rag.chunker import chunker
from app.rag.vector_store import vector_store


class IngestionPipeline:
    async def ingest(
        self,
        pdf_bytes: bytes,
        filename: str,
        vehicle_id: str,
        make: str = "",
        model: str = "",
        year: int = 0,
    ) -> dict:
        pages = pdf_loader.load_from_bytes(pdf_bytes)
        chunks = chunker.chunk_pages(pages)

        vector_store.delete_vehicle(vehicle_id)
        await vector_store.add_chunks(chunks, vehicle_id=vehicle_id, make=make, model=model, year=year)

        return {
            "status": "success",
            "filename": filename,
            "vehicle_id": vehicle_id,
            "pages_processed": len(pages),
            "chunks_created": len(chunks),
        }


ingestion_pipeline = IngestionPipeline()
