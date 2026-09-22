import json
import asyncio
import os
import glob
import sys
from pathlib import Path
from tqdm.asyncio import tqdm
from openai import AsyncOpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import API_URL, API_KEY, MODEL_NAME
from backend.app.core.prompts import RAGAS_JUDGE_PROMPT

# Chế độ Worker cực cao vì API này không bị giới hạn bởi Nvidia
MAX_WORKERS = 50

# Chế độ chạy RAGAS:
# MODE = 0: Xóa toàn bộ điểm cũ, chấm lại từ đầu.
# MODE = 1: Bỏ qua những câu đã chấm, chỉ chấm tiếp những câu chưa chấm (Resume).
MODE = 0

# Bật True nếu muốn test thử 10 câu đầu tiên cho lẹ
LIMIT_10_TEST = False

gemma_client = AsyncOpenAI(base_url=API_URL, api_key=API_KEY)

async def llm_as_a_judge(query: str, generated_answer: str, expected_answer: str, criteria: list, sem: asyncio.Semaphore) -> tuple[float, str]:
    """Gọi Gemma-4 FPT làm Giám khảo độc lập"""
    async with sem:
        criteria_str = "\n".join([f"- {c}" for c in criteria])
        prompt = RAGAS_JUDGE_PROMPT.format(
            query=query,
            expected_answer=expected_answer,
            criteria_str=criteria_str,
            generated_answer=generated_answer
        )

        for _ in range(5): # Retry mạnh mẽ
            try:
                response = await gemma_client.chat.completions.create(
                    model="gemma-4-26B-A4B-it",  # Sử dụng model 26B làm Giám khảo
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                    timeout=60.0
                )
                result = json.loads(response.choices[0].message.content)
                return float(result.get("score", 0)) / 10.0, result.get("reason", "")
            except Exception as e:
                await asyncio.sleep(2)
        return 0.0, "Judge error"

async def evaluate_all():
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding='utf-8')
        
    result_dir = str(PROJECT_ROOT / "results" / "benchmark_latest")
    if not os.path.exists(result_dir):
        print(f"Thư mục {result_dir} không tồn tại. Vui lòng chạy benchmark_nvidia_models.py trước.")
        return

    json_files = glob.glob(f"{result_dir}/detail_*.json")
    if not json_files:
        print("Không tìm thấy file kết quả sinh Text nào để chấm điểm!")
        return

    sem = asyncio.Semaphore(MAX_WORKERS)
    leaderboard = {}

    print(f"🔍 Bắt đầu Đại hội Chấm điểm RAGAS (Worker = {MAX_WORKERS})...")
    
    for file_path in json_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        model_id = data.get("model", "Unknown")
        details = data.get("details", [])
        
        print(f"\n👨‍⚖️ Đang chấm bài cho thí sinh: {model_id}")
        details = data.get("details", [])
        
        # Áp dụng giới hạn 10 câu nếu test
        if LIMIT_10_TEST:
            details = details[:10]

        # Áp dụng MODE để quyết định chấm lại hay resume
        force_re_evaluate = (MODE == 0)
        
        pending_tasks = []
        for item in details:
            if force_re_evaluate or "score" not in item:
                # Tạo Task chấm điểm
                task = llm_as_a_judge(
                    item["query"], 
                    item["generated_answer"], 
                    item["expected_answer"], 
                    item.get("evaluation_criteria", []), 
                    sem
                )
                pending_tasks.append((item, task))

        if not pending_tasks:
            print(f"✨ 100% câu trả lời của {model_id} đã được chấm điểm từ trước!")
        else:
            # Chạy chấm điểm song song
            # WRAP TASK ĐỂ GIỮ VỊ TRÍ INDEX ĐÚNG KHI ASYNC HOÀN THÀNH LỘN XỘN
            async def run_with_index(index, task):
                score, reason = await task
                return index, score, reason
                
            aws = [run_with_index(i, t[1]) for i, t in enumerate(pending_tasks)]
            for i, f in enumerate(tqdm(asyncio.as_completed(aws), total=len(aws), desc=f"Scoring")):
                idx, score, reason = await f
                # Cập nhật trực tiếp vào item gốc dựa vào idx thực tế
                pending_tasks[idx][0]["score"] = score
                pending_tasks[idx][0]["reason"] = reason
                
                # Lưu file liên tục sau mỗi 50 câu để chống cúp điện
                if (i + 1) % 50 == 0:
                    with open(file_path, "w", encoding="utf-8") as file:
                        json.dump(data, file, ensure_ascii=False, indent=2)
            
            # Lưu file lần cuối
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)

        # Tính điểm trung bình của toàn bộ bài thi
        scores = [item["score"] for item in details if "score" in item]
        avg_score = (sum(scores) / len(scores)) * 100 if scores else 0
        data["avg_score"] = avg_score
        data["status"] = "Evaluated"
        leaderboard[model_id] = avg_score
        
        # Lưu đè lại avg_score
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            
        print(f"✅ Đã chấm xong {model_id}. Điểm RAGAS: {avg_score:.2f}%")

    # In Bảng vàng Leaderboard
    leaderboard_file = f"{result_dir}/LEADERBOARD.json"
    sorted_leaderboard = dict(sorted(leaderboard.items(), key=lambda item: item[1], reverse=True))
    with open(leaderboard_file, "w", encoding="utf-8") as f:
        json.dump(sorted_leaderboard, f, ensure_ascii=False, indent=2)

    print("\n" + "="*60)
    print("🏆 BẢNG XẾP HẠNG BENCHMARK (LEADERBOARD) 🏆")
    print("="*60)
    for i, (m, score) in enumerate(sorted_leaderboard.items(), 1):
        print(f"Top {i}: {m:<40} | Điểm RAGAS: {score:>6.2f}%")
    print("="*60)
    print(f"Chi tiết Leaderboard lưu tại: {leaderboard_file}")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(evaluate_all())
