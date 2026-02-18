from app.llm.base import LLMResponse
from app.llm.registry import provider_registry
from app.llm.prompts import SYSTEM_PROMPT, RAG_ANSWER_PROMPT, NO_RAG_ANSWER_PROMPT
from app.rag.vector_store import vector_store


class RAGService:
    async def query(
        self,
        symptom: str,
        vehicle_id: str | None = None,
        make: str = "",
        model: str = "",
        year: int = 0,
    ) -> dict:
        results = await vector_store.search(
            query=symptom,
            vehicle_id=vehicle_id,
            n_results=5,
        )

        has_results = len(results) > 0 and any(r["score"] > 0.3 for r in results)

        if has_results:
            context = "\n\n---\n\n".join(
                [
                    f"【{r['section'] or 'マニュアル'}（p.{r['page']}）】\n{r['content']}"
                    for r in results
                ]
            )
            user_prompt = RAG_ANSWER_PROMPT.format(
                make=make or "不明",
                model=model or "不明",
                year=year or "不明",
                symptom=symptom,
                context=context,
            )
        else:
            user_prompt = NO_RAG_ANSWER_PROMPT.format(
                make=make or "不明",
                model=model or "不明",
                year=year or "不明",
                symptom=symptom,
            )

        provider = provider_registry.get_active()
        if not provider:
            return {
                "answer": "LLMプロバイダーが設定されていません。設定を確認してください。",
                "sources": [],
            }

        llm_response: LLMResponse = await provider.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )

        sources = [
            {
                "content": r["content"][:200],
                "page": r["page"],
                "section": r["section"],
                "score": r["score"],
            }
            for r in results
            if r["score"] > 0.3
        ]

        return {
            "answer": llm_response.content,
            "sources": sources,
        }

    async def get_warnings(self, vehicle_id: str | None, symptom: str) -> list[dict]:
        return await vector_store.search(
            query=symptom,
            vehicle_id=vehicle_id,
            n_results=3,
            warning_only=True,
        )


rag_service = RAGService()
