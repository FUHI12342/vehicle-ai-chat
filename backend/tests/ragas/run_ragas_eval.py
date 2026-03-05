"""
RAGAS評価実行スクリプト

各テストケースの症状でRAG検索 → LLM回答を取得し、
RAGAS の4メトリクスで品質を評価する。

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
            n_results=5,
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


async def evaluate_with_ragas(samples):
    """RAGAS メトリクスで評価実行"""
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


def print_results_table(rag_results: list[dict], ragas_result):
    """結果をコンソールテーブルで表示"""
    df = ragas_result.to_pandas()

    print("\n" + "=" * 100)
    print("RAGAS 評価結果")
    print("=" * 100)

    # 全体スコア
    print("\n■ 全体スコア:")
    for col in df.columns:
        if col not in ("user_input", "response", "retrieved_contexts", "reference"):
            mean_val = df[col].mean()
            print(f"  {col}: {mean_val:.4f}")

    # テストケースごとのスコア
    print("\n■ テストケース別スコア:")
    header = f"{'#':>3} {'カテゴリ':<16} "
    metric_cols = [c for c in df.columns if c not in ("user_input", "response", "retrieved_contexts", "reference")]
    for col in metric_cols:
        short_name = col.replace("_", " ").title()[:12]
        header += f"{short_name:>13} "
    print(header)
    print("-" * len(header))

    for i, tc in enumerate(TEST_CASES):
        row = f"{tc['id']:>3} {tc['category']:<16} "
        for col in metric_cols:
            val = df.iloc[i][col]
            row += f"{val:>13.4f} "
        print(row)

    print("-" * len(header))


def save_results(rag_results: list[dict], ragas_result):
    """結果をJSONファイルに保存"""
    df = ragas_result.to_pandas()
    metric_cols = [c for c in df.columns if c not in ("user_input", "response", "retrieved_contexts", "reference")]

    output = {
        "timestamp": datetime.now().isoformat(),
        "vehicle_id": TEST_CASES[0]["vehicle_id"],
        "overall_scores": {},
        "per_case": [],
    }

    for col in metric_cols:
        output["overall_scores"][col] = round(float(df[col].mean()), 4)

    for i, tc in enumerate(TEST_CASES):
        case_result = {
            "id": tc["id"],
            "category": tc["category"],
            "symptom": tc["symptom"],
            "response_preview": rag_results[i]["response"][:200],
            "contexts_count": len(rag_results[i]["contexts"]),
            "scores": {},
        }
        for col in metric_cols:
            case_result["scores"][col] = round(float(df.iloc[i][col]), 4)
        output["per_case"].append(case_result)

    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_results")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"ragas_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n結果を保存しました: {output_path}")
    return output_path


async def main():
    print("=" * 60)
    print("RAGAS 評価スクリプト")
    print(f"テストケース数: {len(TEST_CASES)}")
    print("=" * 60)

    # Step 1: RAG検索 + LLM回答取得
    print("\n[Step 1] RAG検索 + LLM回答を取得中...")
    rag_results = await run_rag_queries()
    print(f"  完了: {len(rag_results)}件")

    # Step 2: RAGASデータセット構築
    print("\n[Step 2] RAGASデータセットを構築中...")
    samples = build_ragas_dataset(rag_results)
    print(f"  完了: {len(samples)}サンプル")

    # Step 3: RAGAS評価実行
    print("\n[Step 3] RAGAS評価を実行中...")
    ragas_result = await evaluate_with_ragas(samples)

    # Step 4: 結果表示 + 保存
    print_results_table(rag_results, ragas_result)
    save_results(rag_results, ragas_result)


if __name__ == "__main__":
    asyncio.run(main())
