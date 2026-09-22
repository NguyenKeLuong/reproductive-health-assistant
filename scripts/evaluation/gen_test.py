import os
import json
import random
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm

# Tải cấu hình từ .env
load_dotenv()

API_URL = os.getenv("API_URL")
API_KEY = os.getenv("API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME")

# Khởi tạo OpenAI Async Client
client = AsyncOpenAI(
    base_url=API_URL,
    api_key=API_KEY
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Thư mục gốc chứa dữ liệu tri thức
CANDIDATE_KB_DIRS = [
    PROJECT_ROOT / "data" / "knowledge_base",
    PROJECT_ROOT / "co_so_du_lieu_kien_thuc",
    Path("co_so_du_lieu_kien_thuc"),
]
KB_DIR = next((p for p in CANDIDATE_KB_DIRS if p.exists()), CANDIDATE_KB_DIRS[0])
OUTPUT_DIR = PROJECT_ROOT / "data" / "datasets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = str(OUTPUT_DIR / "rag_test_dataset_1000.json")

# 0: Chế độ test (chỉ chạy 10 bài để kiểm tra)
# 1: Chế độ chạy thật (chạy full 1000 bài)
MODE = 1

# Số lượng worker chạy song song (có thể giảm xuống nếu gặp lỗi Rate Limit API)
MAX_CONCURRENT_WORKERS = 50

# Cấu trúc tỷ lệ 1000 câu hỏi (dựa trên mức độ quan trọng & lượng kiến thức)
DISTRIBUTION = {
    "y_khoa_lam_sang": 400,        # Lâm sàng, bệnh lý, triệu chứng rất quan trọng (40%)
    "tong_hop_sinh_san": 200,      # Planned Parenthood - Kiến thức chuẩn mực chung (20%)
    "thuc_hanh_tranh_thai": 150,   # Biện pháp tránh thai thực tiễn (15%)
    "giao_duc_gioi_tinh": 150,     # Tâm lý tuổi dậy thì, giới tính (15%)
    "tam_ly_va_dong_thuan": 100    # Xử lý bạo lực, đồng thuận hẹn hò (10%)
}

SYSTEM_PROMPT = """You are an expert Medical AI data engineer. 
Your task is to generate EXACTLY TWO high-quality JSON Q&A pairs (in Vietnamese) for a RAG evaluation dataset, based purely on the provided English medical text.

Requirements:
1. Return EXACTLY ONE JSON array containing TWO JSON objects.
2. The `user_query` MUST be in natural Vietnamese (casual tone, like asking a doctor). It should be either: Fact-seeking, Situational, Comparison, Emotional, or Myth-busting.
3. The `expected_answer` MUST be in Vietnamese, highly accurate, and derived ONLY from the provided text.
4. The `golden_context` is the EXACT ENGLISH SNIPPET from the text that answers the question. Do not translate the golden_context.

OUTPUT FORMAT (JSON OBJECT):
{
  "qa_pairs": [
    {
      "id": "gen_001_1",
      "metadata": {
        "question_type": "<type>"
      },
      "retrieval_ground_truth": {
        "source_file": "<filename>",
        "golden_chunk": "<exact_english_text_snippet>"
      },
      "generation_ground_truth": {
        "user_query": "<vietnamese_question>",
        "expected_answer": "<vietnamese_answer>",
        "evaluation_criteria": ["<criterion_1>", "<criterion_2>"]
      }
    },
    {
      "id": "gen_001_2",
      "metadata": {
        "question_type": "<type>"
      },
      "retrieval_ground_truth": {
        "source_file": "<filename>",
        "golden_chunk": "<exact_english_text_snippet>"
      },
      "generation_ground_truth": {
        "user_query": "<vietnamese_question>",
        "expected_answer": "<vietnamese_answer>",
        "evaluation_criteria": ["<criterion_1>", "<criterion_2>"]
      }
    }
  ]
}
"""

async def generate_qa_pair(file_path: Path, category: str):
    """Đọc 1 file JSON và yêu cầu LLM sinh đúng 2 câu hỏi."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        text_content = data.get("text", "") or data.get("full_summary", "")
            
        # Cắt bớt ở mức an toàn (6000 ký tự) nếu có file quá khổng lồ, còn lại giữ nguyên full bài
        text_content = text_content[:15000] 
        
        prompt = f"""Source File: {file_path.name}
Category: {category}

Provided Medical Text (English):
\"\"\"{text_content}\"\"\"

Generate EXACTLY TWO Q&A pairs inside a JSON object with the key "qa_pairs"."""

        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}, # Đảm bảo output là JSON
            temperature=0.3,
            max_tokens=4000
        )
        
        output = response.choices[0].message.content
        if output.startswith("```json"):
            output = output[7:-3]
        elif output.startswith("```"):
            output = output[3:-3]
            
        parsed = json.loads(output)
        
        results_list = []
        qa_pairs = []
        if isinstance(parsed, dict):
            # Lấy list từ key 'qa_pairs' hoặc fallback nếu có các key tương tự
            if "qa_pairs" in parsed:
                qa_pairs = parsed["qa_pairs"]
            elif "questions" in parsed:
                qa_pairs = parsed["questions"]
            else:
                # Nếu LLM vẫn trả về 1 object trực tiếp
                qa_pairs = [parsed]
        elif isinstance(parsed, list):
            qa_pairs = parsed

        for idx, item in enumerate(qa_pairs):
            if isinstance(item, dict) and "generation_ground_truth" in item:
                item["id"] = f"{file_path.stem}_{idx+1}"
                results_list.append(item)
            
        return results_list
        
        
    except Exception as e:
        print(f"\n[!] Lỗi xử lý {file_path.name}: {e}")
        return None

async def main():
    print(f"Bắt đầu chuẩn bị tài liệu sinh Test Dataset (MODE = {MODE})...")
    tasks = []
    
    # Duyệt toàn bộ file trong các thư mục, 1 file sinh 2 câu
    for category in DISTRIBUTION.keys():
        folder_path = KB_DIR / category
        if not folder_path.exists():
            continue
            
        files = list(folder_path.glob("*.json"))
        for file_path in files:
            tasks.append(generate_qa_pair(file_path, category))
            
    # Xáo trộn ngẫu nhiên để lấy đủ các category nếu bị cắt
    random.shuffle(tasks)
    
    if MODE == 0:
        print("--- ĐANG Ở CHẾ ĐỘ TEST: CHỈ CHẠY 10 CÂU ---")
        tasks = tasks[:10]
        OUTPUT_FILE_RUNTIME = "test_10_samples.json"
    else:
        print(f"--- ĐANG Ở CHẾ ĐỘ FULL: CHẠY TOÀN BỘ {len(tasks)} CÂU ---")
        OUTPUT_FILE_RUNTIME = OUTPUT_FILE
        
    print(f"Đã lên lịch {len(tasks)} tasks gọi API. Bắt đầu sinh với {MAX_CONCURRENT_WORKERS} workers song song...")
    
    # Chạy song song giới hạn số request cùng lúc
    results = []
    sem = asyncio.Semaphore(MAX_CONCURRENT_WORKERS)
    
    async def sem_task(t):
        async with sem:
            return await t
            
    for f in tqdm(asyncio.as_completed([sem_task(t) for t in tasks]), total=len(tasks)):
        qa_objs = await f
        if qa_objs and isinstance(qa_objs, list):
            results.extend(qa_objs)
        
    print(f"\nĐã sinh thành công {len(results)} câu hỏi.")
    with open(OUTPUT_FILE_RUNTIME, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
            
    print(f"Đã lưu dataset vào: {OUTPUT_FILE_RUNTIME}")

if __name__ == "__main__":
    asyncio.run(main())
