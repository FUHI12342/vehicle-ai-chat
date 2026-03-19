"""
RAGAS評価実行スクリプト

各テストケースの症状でRAG検索 → LLM回答を取得し、
RAGAS の4メトリクスで品質を評価する。

v6: covered/not_covered分離評価 + カスタムメトリクス
- coveredケース: RAGAS 4メトリクス + procedure_adherence
- not_coveredケース: not_covered_quality (ディーラー誘導/捏造検出/forbidden_terms)

使い方:
  cd backend
  python -m tests.ragas.run_ragas_eval
"""

import asyncio
import json
import sys
import os
from datetime import datetime

# backendディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# .envからOPENAI_API_KEYを環境変数にロード（RAGAS内部のOpenAIクライアントが参照する）
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from tests.ragas.test_cases import TEST_CASES, VEHICLE_MAKE, VEHICLE_MODEL, VEHICLE_YEAR
from tests.ragas.custom_metrics import procedure_adherence, not_covered_quality
from app.utils.fabrication_patterns import detect_fabrications

# ground_truth に「記載なし」を含む = not_coveredケース
NOT_COVERED_IDS = {
    tc["id"]
    for tc in TEST_CASES
    if "記載なし" in tc["ground_truth"] or "記載されていません" in tc["ground_truth"]
}

DEALER_KEYWORDS = ["ディーラー", "販売店", "点検", "ロードサービス", "Honda"]


async def run_rag_queries() -> list[dict]:
    """各テストケースでRAG検索 + LLM回答を取得"""
    from app.rag.vector_store import vector_store
    from app.services.rag_service import rag_service
    from app.llm.registry import provider_registry

    # スクリプト単独実行時はFastAPIの初期化が走らないため手動で初期化
    if not provider_registry.providers:
        provider_registry.initialize()

    results = []
    for tc in TEST_CASES:
        print(f"  [{tc['id']:02d}] {tc['category']}: {tc['symptom'][:30]}...")

        # RAG検索（コンテキスト取得）
        search_results = await vector_store.search(
            query=tc["symptom"],
            vehicle_id=tc["vehicle_id"],
            n_results=10,
        )
        contexts = [r["content"] for r in search_results]

        # RAGService経由でLLM回答取得
        rag_result = await rag_service.query(
            symptom=tc["symptom"],
            vehicle_id=tc["vehicle_id"],
            make=VEHICLE_MAKE,
            model=VEHICLE_MODEL,
            year=VEHICLE_YEAR,
        )

        results.append({
            "test_case": tc,
            "contexts": contexts,
            "response": rag_result["answer"],
            "sources": rag_result["sources"],
        })

    return results


def _split_by_coverage(rag_results: list[dict]) -> tuple[list[dict], list[dict]]:
    """covered/not_covered でケースを分離する。"""
    covered = [r for r in rag_results if r["test_case"]["id"] not in NOT_COVERED_IDS]
    not_covered = [r for r in rag_results if r["test_case"]["id"] in NOT_COVERED_IDS]
    return covered, not_covered


def build_ragas_dataset(rag_results: list[dict]):
    """RAG結果をRAGAS SingleTurnSampleのリストに変換"""
    from ragas import SingleTurnSample

    samples = []
    for r in rag_results:
        sample = SingleTurnSample(
            user_input=r["test_case"]["symptom"],
            response=r["response"],
            retrieved_contexts=r["contexts"],
            reference=r["test_case"]["ground_truth"],
        )
        samples.append(sample)
    return samples


def compute_not_covered_adherence(response: str) -> float:
    """not_coveredケース向け後方互換メトリクス。"""
    has_dealer = any(kw in response for kw in DEALER_KEYWORDS)
    has_fabrication = len(detect_fabrications(response)) > 0
    if has_fabrication:
        return 0.0
    if has_dealer:
        return 1.0
    return 0.3


async def evaluate_with_ragas(samples):
    """RAGAS メトリクスで評価実行（coveredケースのみ）"""
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)

    from ragas import EvaluationDataset, evaluate
    from ragas.metrics import (
        Faithfulness,
        ResponseRelevancy,
        LLMContextPrecisionWithoutReference,
        LLMContextRecall,
    )
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings

    dataset = EvaluationDataset(samples=samples)

    evaluator_llm = LangchainLLMWrapper(ChatOpenAI(model="gpt-4o-mini"))
    evaluator_emb = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model="text-embedding-3-small"))

    metrics = [
        Faithfulness(llm=evaluator_llm),
        ResponseRelevancy(llm=evaluator_llm, embeddings=evaluator_emb),
        LLMContextPrecisionWithoutReference(llm=evaluator_llm),
        LLMContextRecall(llm=evaluator_llm),
    ]

    result = evaluate(
        dataset=dataset,
        metrics=metrics,
    )

    return result


def print_results_table(
    covered_results: list[dict],
    not_covered_results: list[dict],
    ragas_result,
    nc_scores: list[dict],
    pa_scores: list[dict] | None = None,
):
    """結果をコンソールテーブルで表示"""
    df = ragas_result.to_pandas()

    print("\n" + "=" * 100)
    print("RAGAS 評価結果 (v6: covered/not_covered分離 + カスタムメトリクス)")
    print("=" * 100)

    # --- Covered ---
    print(f"\n■ Covered ケース ({len(covered_results)}件) — RAGAS 4メトリクス:")
    metric_cols = [c for c in df.columns if c not in ("user_input", "response", "retrieved_contexts", "reference")]
    for col in metric_cols:
        mean_val = df[col].mean()
        print(f"  {col}: {mean_val:.4f}")

    # procedure_adherence平均
    if pa_scores:
        pa_values = [s["procedure_adherence"] for s in pa_scores if s["procedure_adherence"] is not None]
        if pa_values:
            print(f"  procedure_adherence: {sum(pa_values)/len(pa_values):.4f}")

    print(f"\n  {'#':>3} {'カテゴリ':<16} ", end="")
    for col in metric_cols:
        short_name = col.replace("_", " ").title()[:12]
        print(f"{short_name:>13} ", end="")
    print(f"{'ProcAdhere':>13} ")
    print("  " + "-" * 95)

    for i, r in enumerate(covered_results):
        tc = r["test_case"]
        print(f"  {tc['id']:>3} {tc['category']:<16} ", end="")
        for col in metric_cols:
            val = df.iloc[i][col]
            print(f"{val:>13.4f} ", end="")
        pa_val = pa_scores[i]["procedure_adherence"] if pa_scores and i < len(pa_scores) else None
        if pa_val is not None:
            print(f"{pa_val:>13.4f} ", end="")
        else:
            print(f"{'N/A':>13} ", end="")
        print()

    # --- Not Covered ---
    print(f"\n■ Not Covered ケース ({len(not_covered_results)}件) — not_covered_quality:")
    if nc_scores:
        mean_nc = sum(s["not_covered_adherence"] for s in nc_scores) / len(nc_scores)
        mean_quality = sum(s["not_covered_quality"] for s in nc_scores) / len(nc_scores)
        print(f"  平均 not_covered_adherence: {mean_nc:.4f}")
        print(f"  平均 not_covered_quality:   {mean_quality:.4f}")
        print(f"\n  {'#':>3} {'カテゴリ':<16} {'adherence':>10} {'quality':>10} {'dealer':>8} {'forbidden':>10}")
        print("  " + "-" * 65)
        for s in nc_scores:
            print(
                f"  {s['id']:>3} {s['category']:<16} "
                f"{s['not_covered_adherence']:>10.4f} "
                f"{s['not_covered_quality']:>10.4f} "
                f"{'OK' if s['has_dealer'] else 'NG':>8} "
                f"{'NG' if s['has_forbidden_terms'] else 'OK':>10}"
            )

    print("\n" + "=" * 100)


def save_results(
    covered_results: list[dict],
    not_covered_results: list[dict],
    ragas_result,
    nc_scores: list[dict],
    pa_scores: list[dict] | None = None,
):
    """結果をJSONファイルに保存"""
    df = ragas_result.to_pandas()
    metric_cols = [c for c in df.columns if c not in ("user_input", "response", "retrieved_contexts", "reference")]

    output = {
        "timestamp": datetime.now().isoformat(),
        "vehicle_id": TEST_CASES[0]["vehicle_id"],
        "evaluation_mode": "split_covered_not_covered_v6",
        "covered": {
            "count": len(covered_results),
            "overall_scores": {},
            "per_case": [],
        },
        "not_covered": {
            "count": len(not_covered_results),
            "overall_scores": {},
            "per_case": nc_scores,
        },
    }

    for col in metric_cols:
        output["covered"]["overall_scores"][col] = round(float(df[col].mean()), 4)

    # procedure_adherence平均
    if pa_scores:
        pa_values = [s["procedure_adherence"] for s in pa_scores if s["procedure_adherence"] is not None]
        if pa_values:
            output["covered"]["overall_scores"]["procedure_adherence"] = round(
                sum(pa_values) / len(pa_values), 4
            )

    for i, r in enumerate(covered_results):
        tc = r["test_case"]
        case_result = {
            "id": tc["id"],
            "category": tc["category"],
            "symptom": tc["symptom"],
            "response_preview": r["response"][:200],
            "contexts_count": len(r["contexts"]),
            "scores": {},
        }
        for col in metric_cols:
            case_result["scores"][col] = round(float(df.iloc[i][col]), 4)
        if pa_scores and i < len(pa_scores):
            pa_val = pa_scores[i]["procedure_adherence"]
            case_result["scores"]["procedure_adherence"] = round(pa_val, 4) if pa_val is not None else None
        output["covered"]["per_case"].append(case_result)

    if nc_scores:
        output["not_covered"]["overall_scores"]["not_covered_adherence"] = round(
            sum(s["not_covered_adherence"] for s in nc_scores) / len(nc_scores), 4
        )
        output["not_covered"]["overall_scores"]["not_covered_quality"] = round(
            sum(s["not_covered_quality"] for s in nc_scores) / len(nc_scores), 4
        )

    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_results")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"ragas_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n結果を保存しました: {output_path}")
    return output_path


async def main():
    print("=" * 60)
    print("RAGAS 評価スクリプト (v6: covered/not_covered分離 + カスタムメトリクス)")
    print(f"テストケース数: {len(TEST_CASES)} (covered: {len(TEST_CASES) - len(NOT_COVERED_IDS)}, not_covered: {len(NOT_COVERED_IDS)})")
    print("=" * 60)

    # Step 1: RAG検索 + LLM回答取得
    print("\n[Step 1] RAG検索 + LLM回答を取得中...")
    rag_results = await run_rag_queries()
    print(f"  完了: {len(rag_results)}件")

    # Step 2: covered/not_covered分離
    covered_results, not_covered_results = _split_by_coverage(rag_results)
    print(f"\n[Step 2] 分離: covered={len(covered_results)}件, not_covered={len(not_covered_results)}件")

    # Step 3a: RAGAS評価 (coveredケースのみ)
    print("\n[Step 3a] RAGAS評価 (coveredケース)...")
    covered_samples = build_ragas_dataset(covered_results)
    ragas_result = await evaluate_with_ragas(covered_samples)

    # Step 3b: not_covered評価（enhanced with not_covered_quality）
    print("\n[Step 3b] not_covered評価...")
    nc_scores = []
    for r in not_covered_results:
        tc = r["test_case"]
        response = r["response"]
        adherence = compute_not_covered_adherence(response)
        quality = not_covered_quality(
            response=response,
            forbidden_terms=tc.get("forbidden_terms"),
            expected_final_action=tc.get("expected_final_action"),
        )
        nc_scores.append({
            "id": tc["id"],
            "category": tc["category"],
            "symptom": tc["symptom"],
            "response_preview": response[:200],
            "not_covered_adherence": adherence,
            "not_covered_quality": quality["score"],
            "has_dealer": quality["has_dealer_referral"],
            "has_fabrication": quality["has_forbidden_terms"],
            "has_forbidden_terms": quality["has_forbidden_terms"],
        })

    # Step 3c: procedure_adherence評価（coveredケース）
    print("\n[Step 3c] procedure_adherence評価...")
    pa_scores = []
    for r in covered_results:
        tc = r["test_case"]
        manual_steps = tc.get("manual_steps", [])
        if manual_steps:
            score = procedure_adherence(
                conversation_log=[r["response"]],
                manual_steps=manual_steps,
            )
        else:
            score = None  # 手順なしケースはスキップ
        pa_scores.append({
            "id": tc["id"],
            "category": tc["category"],
            "procedure_adherence": score,
        })

    # Step 4: 結果表示 + 保存
    print_results_table(covered_results, not_covered_results, ragas_result, nc_scores, pa_scores)
    save_results(covered_results, not_covered_results, ragas_result, nc_scores, pa_scores)


if __name__ == "__main__":
    asyncio.run(main())
