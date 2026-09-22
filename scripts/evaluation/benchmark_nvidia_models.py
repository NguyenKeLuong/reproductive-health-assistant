import os
import json
import asyncio
import httpx
import sys
from pathlib import Path
from datetime import datetime
from tqdm.asyncio import tqdm
from qdrant_client import QdrantClient
from openai import AsyncOpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import API_URL, API_KEY, MODEL_NAME, NVIDIA_API_KEY, NVIDIA_API_KEY_2, NVIDIA_API_KEY_3, NVIDIA_SPEECH_API_URL

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# ===============================
# Config Benchmark
# ===============================
CANDIDATE_DATASET_PATHS = [
    PROJECT_ROOT / "data" / "datasets" / "rag_test_dataset_embedded.json",
    PROJECT_ROOT / "rag_test_dataset_embedded.json",
    Path("rag_test_dataset_embedded.json"),
]
TEST_EMBEDDED_FILE = str(next((p for p in CANDIDATE_DATASET_PATHS if p.exists()), CANDIDATE_DATASET_PATHS[0]))
COLLECTION_NAME = "reproductive_health_kb"
QDRANT_STORAGE_PATH = str(PROJECT_ROOT / "qdrant_data")

# Chế độ chạy: 0 = Test nhanh 10 câu, 1 = Chạy thật full 1000 câu
MODE = 1 
# Mỗi API Key chạy đúng 3 luồng (Worker=3) để êm ái dưới 40 RPM. 3 Keys = 9 Workers
MAX_WORKERS = 9 

TOP_K_RETRIEVAL = 30
TOP_N_RERANK = 10
TOP_K_GEN = 5

NVIDIA_RERANK_URL = "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking"
RERANK_MODEL = "nv-rerank-qa-mistral-4b:1"

# Danh sách 3 API Keys của bạn để Load Balancing (Vượt rào 40 RPM)
NVIDIA_API_KEYS = [k for k in [NVIDIA_API_KEY, NVIDIA_API_KEY_2, NVIDIA_API_KEY_3] if k]

# Danh sách các Model Sinh văn bản (Generator) của Nvidia còn hoạt động tốt
MODELS_TO_TEST = [
    MODEL_NAME,                              # Model gốc của bạn (Qua API FPT/OpenAI)
    "meta/llama-3.1-70b-instruct",           # Phiên bản Llama 3.1 70B chuẩn mực (Top 1)
    "meta/llama-3.1-8b-instruct",            # Llama 8B tốc độ cao (Top 2)
    "meta/llama-3.2-3b-instruct",            # Phiên bản siêu tốc (Top 3)
]

# Client Pool
fpt_judge_client = AsyncOpenAI(base_url=API_URL, api_key=API_KEY) # Dùng API của bạn làm Giám khảo chung
# Khởi tạo trước một bộ từ điển các Client của Nvidia để dùng lại (tái sử dụng kết nối mạng)
nvidia_clients_dict = {key: AsyncOpenAI(base_url=NVIDIA_SPEECH_API_URL, api_key=key) for key in NVIDIA_API_KEYS}

# ===============================
# Functions
# ===============================
async def rerank_passages(client: httpx.AsyncClient, query: str, passages: list, top_n: int, assigned_key: str):
    headers = {"Authorization": f"Bearer {assigned_key}", "Accept": "application/json"}
    payload = {
        "model": RERANK_MODEL,
        "query": {"text": query},
        "passages": [{"text": p["text"][:12000]} for p in passages],
        "top_n": top_n
    }
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = await client.post(NVIDIA_RERANK_URL, headers=headers, json=payload, timeout=20.0)
            if response.status_code == 200:
                ranked_indices = [item["index"] for item in response.json().get("rankings", [])]
                return [passages[i] for i in ranked_indices]
            elif response.status_code == 429:
                await asyncio.sleep(2.0 * (2 ** attempt)) # Nếu dính 429 thì ngủ 1 chút
                continue
            else:
                break
        except Exception:
            await asyncio.sleep(2.0)
    return passages[:top_n]

async def generate_rag_answer_nvidia(model_id: str, query: str, contexts: list, assigned_key: str, agent_name: str) -> str:
    """Gọi Nvidia API để sinh câu trả lời bằng API Key được phân công, sử dụng Prompt chuẩn của hệ thống"""
    # Trộn tài liệu
    context_str = "\n\n---\n\n".join([p["text"] for p in contexts])
    
    # Map tên Agent sang Prompt tương ứng
    from backend.app.core import prompts as prompt_agent
    prompt_mapping = {
        "general_health_agent": prompt_agent.GENERAL_HEALTH_PROMPT,
        "sti_agent": prompt_agent.STI_AGENT_PROMPT,
        "contraception_agent": prompt_agent.CONTRACEPTION_AGENT_PROMPT,
        "reproductive_health_agent": prompt_agent.REPRODUCTIVE_HEALTH_AGENT_PROMPT,
        "safety_consent_agent": prompt_agent.SAFETY_CONSENT_AGENT_PROMPT
    }
    
    # Lấy đúng Prompt chuyên môn, nếu lỗi hoặc không khớp thì fallback về General
    agent_prompt = prompt_mapping.get(agent_name, prompt_agent.GENERAL_HEALTH_PROMPT)
    
    # Kết hợp Prompt chuẩn + Tài liệu tham khảo
    system_prompt = agent_prompt + "\n\n[TÀI LIỆU THAM KHẢO RAG (Hãy dựa vào đây để trả lời chính xác)]:\n" + context_str
    
    if model_id == MODEL_NAME:
        current_client = fpt_judge_client
    else:
        current_client = nvidia_clients_dict[assigned_key]
        
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = await current_client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                temperature=0.1,
                max_tokens=512,
                timeout=120.0 # Tăng hẳn lên 120s cho 70B
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate limit" in err_str.lower() or "timeout" in err_str.lower():
                await asyncio.sleep(2.0 * (2 ** attempt))
                continue
            print(f"\n[CẢNH BÁO] Model {model_id} bị lỗi API: {err_str}")
            return f"Error generation: {err_str}"
    print(f"\n[CẢNH BÁO] Model {model_id} lỗi Rate Limit quá nhiều lần!")
    return "Error generation: Max retries exceeded (Rate Limited)"

async def process_single_case(qdrant, http_client, model_id, tc, sem, assigned_key, rerank_cache):
    async with sem:
        query_vector = tc["user_query_embedding"]
        query_text = tc["generation_ground_truth"]["user_query"]
        expected_ans = tc["generation_ground_truth"]["expected_answer"]
        criteria = tc["generation_ground_truth"]["evaluation_criteria"]
        
        # BỘ NHỚ ĐỆM (CACHE) RERANK ĐỂ KHÔNG PHẢI GỌI LẠI LẦN NỮA CHO CÁC MODEL SAU
        if query_text in rerank_cache:
            reranked = rerank_cache[query_text]
        else:
            # 1. Truy xuất
            search_result = qdrant.query_points(collection_name=COLLECTION_NAME, query=query_vector, limit=TOP_K_RETRIEVAL).points
            passages = [{"source_file": hit.payload["source_file"], "text": hit.payload["text"]} for hit in search_result]
            
            # 2. Rerank (Gọi bằng key được cấp)
            reranked = await rerank_passages(http_client, query_text, passages, TOP_N_RERANK, assigned_key)
            rerank_cache[query_text] = reranked
        
        # Lấy nhãn chuyên môn (Nếu file route_dataset.py chưa chạy kịp thì fallback về general)
        agent_name = tc.get("assigned_agent", "general_health_agent")
        
        # 3. Generation (Gọi bằng key được cấp và ép Prompt đúng chuyên môn)
        generated_ans = await generate_rag_answer_nvidia(model_id, query_text, reranked[:TOP_K_GEN], assigned_key, agent_name)
        
        return {
            "query": query_text,
            "assigned_agent": agent_name,
            "expected_answer": expected_ans,
            "evaluation_criteria": criteria,
            "generated_answer": generated_ans
        }

async def benchmark_models():
    print(f"Đang đọc dữ liệu Test từ {TEST_EMBEDDED_FILE}...")
    try:
        with open(TEST_EMBEDDED_FILE, "r", encoding="utf-8") as f:
            test_cases = json.load(f)
    except Exception:
        print("LỖI: Không tìm thấy file Test.")
        return

    if MODE == 0:
        test_cases = test_cases[:10]
        print("--- ĐANG Ở CHẾ ĐỘ TEST (Chạy 10 câu) ---")

    qdrant = QdrantClient(path=QDRANT_STORAGE_PATH)
    
    result_dir = str(PROJECT_ROOT / "results" / "benchmark_latest")
    os.makedirs(result_dir, exist_ok=True)
    
    # --- RERANK CACHE LƯU TRỮ ---
    cache_file = f"{result_dir}/rerank_cache.json"
    rerank_cache = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                rerank_cache = json.load(f)
            print(f"📦 Đã nạp {len(rerank_cache)} kết quả Rerank từ bộ nhớ đệm!")
        except:
            pass

    async with httpx.AsyncClient() as http_client:
        for model_id in MODELS_TO_TEST:
            current_workers = 50 if model_id == MODEL_NAME else MAX_WORKERS
            sem = asyncio.Semaphore(current_workers)
            
            print(f"\n🚀 ĐANG CHẠY BENCHMARK CHO MODEL: {model_id} (Workers: {current_workers})")
            model_safe_name = model_id.replace("/", "_")
            out_file = f"{result_dir}/detail_{model_safe_name}.json"
            
            # --- TÍNH NĂNG RESUME (CHECKPOINT) ---
            results = []
            done_queries = set()
            if os.path.exists(out_file):
                try:
                    with open(out_file, "r", encoding="utf-8") as f:
                        old_data = json.load(f)
                        results = old_data.get("details", [])
                        done_queries = {r["query"] for r in results}
                    print(f"🔄 Đã tìm thấy file lưu trước đó. Khôi phục {len(results)} câu hỏi đã chạy xong, bỏ qua không chạy lại.")
                except:
                    pass
            
            # Lọc ra những câu chưa chạy
            pending_cases = []
            for tc in test_cases:
                if tc["generation_ground_truth"]["user_query"] not in done_queries:
                    pending_cases.append(tc)
            
            if not pending_cases:
                print(f"✨ Model {model_id} đã hoàn thành 100% từ trước!")
                continue
            
            # Chia dữ liệu tĩnh: Ép cứng mỗi câu hỏi cho 1 Key cụ thể dựa vào index
            tasks = []
            for i, tc in enumerate(pending_cases):
                assigned_key = NVIDIA_API_KEYS[i % len(NVIDIA_API_KEYS)]
                tasks.append(process_single_case(qdrant, http_client, model_id, tc, sem, assigned_key, rerank_cache))
                
            # Duyệt qua các task và LƯU LIÊN TỤC
            for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc=f"Eval {model_id.split('/')[-1]}"):
                res = await f
                results.append(res)
                
                # LƯU FILE NGAY LẬP TỨC
                with open(out_file, "w", encoding="utf-8") as file:
                    json.dump({"model": model_id, "status": "Generated", "details": results}, file, ensure_ascii=False, indent=2)
                
                # LƯU CACHE RERANK ĐỂ CÁC MODEL SAU DÙNG KÉ
                with open(cache_file, "w", encoding="utf-8") as cfile:
                    json.dump(rerank_cache, cfile, ensure_ascii=False, indent=2)
            
            print(f"✅ Xong sinh text cho {model_id}! Lưu tại {out_file}")

    print("\n" + "="*60)
    print("HOÀN THÀNH GIAI ĐOẠN SINH CÂU TRẢ LỜI CHO 10 MODELS!")
    print("Hãy chạy file evaluate_ragas.py để Giám khảo chấm điểm toàn bộ.")
    print("="*60)
    print(f"📁 Toàn bộ chi tiết lưu tại thư mục: {result_dir}")

if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(benchmark_models())
