import json
import asyncio
import httpx
import os
import sys
from pathlib import Path
from tqdm.asyncio import tqdm
from qdrant_client import QdrantClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import NVIDIA_API_KEY

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# ===============================
# Config & Path Resolution
# ===============================
CANDIDATE_DATASET_PATHS = [
    PROJECT_ROOT / "data" / "datasets" / "rag_test_dataset_embedded.json",
    PROJECT_ROOT / "rag_test_dataset_embedded.json",
    Path("rag_test_dataset_embedded.json"),
]
TEST_EMBEDDED_FILE = str(next((p for p in CANDIDATE_DATASET_PATHS if p.exists()), CANDIDATE_DATASET_PATHS[0]))
COLLECTION_NAME = "reproductive_health_kb"
QDRANT_STORAGE_PATH = str(PROJECT_ROOT / "qdrant_data")
RESULTS_DIR = PROJECT_ROOT / "results"
NVIDIA_RERANK_URL = "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking"
RERANK_MODEL = "nv-rerank-qa-mistral-4b:1"

TOP_K_RETRIEVAL = 30  # Lấy 30 bài bằng Vector Search
TOP_N_RERANK = 10     # Rerank lại để chốt Top 10 (phục vụ tính toán @1, @3, @5, @10)

MODE = 0  # 0: Đánh giá thuần Qdrant (Không Rerank), 1: Đánh giá có Rerank Mistral

async def rerank_passages(client: httpx.AsyncClient, query: str, passages: list, top_n: int = 5):
    """Gọi API Nvidia Rerank để chấm điểm lại danh sách passages"""
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Accept": "application/json"
    }
    
    payload = {
        "model": RERANK_MODEL,
        "query": {"text": query},
        "passages": [{"text": p["text"][:12000]} for p in passages], # Cắt bớt 12000 ký tự đầu để không bị lỗi 8192 tokens của Reranker
        "top_n": top_n
    }
    
    max_retries = 5
    base_delay = 2.0
    
    for attempt in range(max_retries):
        try:
            response = await client.post(NVIDIA_RERANK_URL, headers=headers, json=payload, timeout=30.0)
            if response.status_code == 200:
                data = response.json()
                ranked_indices = [item["index"] for item in data.get("rankings", [])]
                return [passages[i] for i in ranked_indices]
            elif response.status_code == 429:
                # Quá tải RPM, ngủ một lúc rồi thử lại
                await asyncio.sleep(base_delay * (2 ** attempt))
                continue
            else:
                print(f"Rerank API Error: {response.text}")
                return passages[:top_n] # Fallback
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Rerank Exception: {e}")
                return passages[:top_n]
            await asyncio.sleep(base_delay)

async def evaluate_rag():
    print(f"Đang đọc dữ liệu Test từ {TEST_EMBEDDED_FILE}...")
    try:
        with open(TEST_EMBEDDED_FILE, "r", encoding="utf-8") as f:
            test_cases = json.load(f)
    except FileNotFoundError:
        print(f"LỖI: Không tìm thấy {TEST_EMBEDDED_FILE}.")
        return

    qdrant = QdrantClient(path=QDRANT_STORAGE_PATH)
    
    hits_count_at = {1: 0, 3: 0, 5: 0, 10: 0}
    mrr_score_at = {1: 0.0, 3: 0.0, 5: 0.0, 10: 0.0}
    total_cases = len(test_cases)
    
    os.makedirs(str(RESULTS_DIR), exist_ok=True)
    out_file = str(RESULTS_DIR / ("retrieval_details_no_rerank.json" if MODE == 0 else "retrieval_details.json"))
    
    # --- RERANK CACHE LƯU TRỮ (Dùng chung cho Benchmark) ---
    cache_dir = str(RESULTS_DIR / "benchmark_latest")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = f"{cache_dir}/rerank_cache.json"
    rerank_cache = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                rerank_cache = json.load(f)
        except:
            pass
    
    # --- TÍNH NĂNG RESUME (CHECKPOINT) ---
    detailed_results = []
    done_queries = set()
    if os.path.exists(out_file):
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                detailed_results = json.load(f)
                done_queries = {r["query"] for r in detailed_results}
            print(f"🔄 Đã tìm thấy file lưu trước đó. Khôi phục {len(detailed_results)} câu hỏi đã đánh giá, bỏ qua không chạy lại.")
        except:
            pass

    # Lọc ra những câu chưa chạy
    pending_cases = [tc for tc in test_cases if tc["generation_ground_truth"]["user_query"] not in done_queries]
    
    if not pending_cases:
        print("✨ Đã hoàn thành đánh giá 100% từ trước!")
    else:
        print(f"Bắt đầu đánh giá RAG: Lấy Top {TOP_K_RETRIEVAL} -> Rerank Top {TOP_N_RERANK}...")
    
    async with httpx.AsyncClient() as http_client:
        for i, tc in enumerate(tqdm(pending_cases, desc="Evaluating Retrieval")):
            query_vector = tc["user_query_embedding"]
            query_text = tc["generation_ground_truth"]["user_query"]
            ground_truth_file = tc["retrieval_ground_truth"]["source_file"]
            
            # BƯỚC 1: DENSE RETRIEVAL
            search_result = qdrant.query_points(collection_name=COLLECTION_NAME, query=query_vector, limit=TOP_K_RETRIEVAL).points
            
            passages = [{"source_file": hit.payload["source_file"], "text": hit.payload["text"]} for hit in search_result]
                
            # BƯỚC 2: RERANKING
            if MODE == 1:
                if query_text in rerank_cache:
                    reranked_passages = rerank_cache[query_text]
                else:
                    reranked_passages = await rerank_passages(http_client, query_text, passages, TOP_N_RERANK)
                    # Lưu vào cache để nuôi con Benchmark chạy sau
                    rerank_cache[query_text] = reranked_passages
                    with open(cache_file, "w", encoding="utf-8") as cfile:
                        json.dump(rerank_cache, cfile, ensure_ascii=False, indent=2)
            else:
                # Thuần Qdrant: Không Rerank, lấy luôn top K từ Dense Search
                reranked_passages = passages[:TOP_N_RERANK]
            
            # BƯỚC 3: ĐÁNH GIÁ (Kiểm tra Hit Rate và MRR cho nhiều K)
            hit_rank = -1
            for rank, p in enumerate(reranked_passages):
                if p["source_file"] == ground_truth_file:
                    hit_rank = rank + 1
                    break
            
            detailed_results.append({
                "query": query_text,
                "expected_source": ground_truth_file,
                "hit_rank": hit_rank,
                "top_1_source": reranked_passages[0]["source_file"] if reranked_passages else None
            })
            
            # LƯU FILE LIÊN TỤC (CHỐNG MẤT ĐIỆN)
            with open(out_file, "w", encoding="utf-8") as file:
                json.dump(detailed_results, file, ensure_ascii=False, indent=2)

    # TÍNH TOÁN LẠI TỪ TOÀN BỘ FILE JSON
    total_cases = len(detailed_results)
    if total_cases == 0:
        return
        
    for res in detailed_results:
        rank = res["hit_rank"]
        if rank != -1:
            for k in [1, 3, 5, 10]:
                if rank <= k:
                    hits_count_at[k] += 1
                    mrr_score_at[k] += (1.0 / rank)

    print("\n" + "="*60)
    print("KẾT QUẢ ĐÁNH GIÁ RAG (RETRIEVAL METRICS)")
    print("="*60)
    print(f"Tổng số câu hỏi Test : {total_cases}")
    method_str = f"Thuần Dense Search Qdrant (Top {TOP_N_RERANK}) - KHÔNG RERANK" if MODE == 0 else f"Dense Search (Top {TOP_K_RETRIEVAL}) + Rerank Mistral-4B (Top {TOP_N_RERANK})"
    print(f"Phương pháp          : {method_str}\n")
    
    for k in [1, 3, 5, 10]:
        hit_rate = (hits_count_at[k] / total_cases) * 100
        recall = hit_rate # Vì dataset có 1 ground truth source_file/query, Recall = Hit Rate
        mrr = mrr_score_at[k] / total_cases
        print(f"Metrics @ {k:<2} | Hit Rate: {hit_rate:>6.2f}% | Recall: {recall:>6.2f}% | MRR: {mrr:.4f}")
    print("="*60)

if __name__ == "__main__":
    # Fix cho Windows để chạy asyncio tránh lỗi EventLoop
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(evaluate_rag())
