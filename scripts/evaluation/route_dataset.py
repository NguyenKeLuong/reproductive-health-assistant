import json
import asyncio
import os
import sys
from pathlib import Path
from tqdm.asyncio import tqdm

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.agents.coordinator import CoordinatorAgent

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

CANDIDATE_DATASET_PATHS = [
    PROJECT_ROOT / "data" / "datasets" / "rag_test_dataset_embedded.json",
    PROJECT_ROOT / "rag_test_dataset_embedded.json",
    Path("rag_test_dataset_embedded.json"),
]
DATASET_FILE = str(next((p for p in CANDIDATE_DATASET_PATHS if p.exists()), CANDIDATE_DATASET_PATHS[0]))

MODE = 1  # 0: Chỉ test thử 10 câu, 1: Chạy dán nhãn toàn bộ 1000 câu

async def route_all_questions():
    print(f"Đang đọc dữ liệu từ {DATASET_FILE}...")
    if not os.path.exists(DATASET_FILE):
        print(f"LỖI: Không tìm thấy file {DATASET_FILE}")
        return

    with open(DATASET_FILE, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    already_routed = sum(1 for tc in dataset if "assigned_agent" in tc)
    pending_cases = [tc for tc in dataset if "assigned_agent" not in tc]

    if MODE == 0:
        pending_cases = pending_cases[:10]
        print("🛠️ Đang chạy ở MODE = 0 (Chỉ dán nhãn 10 câu đầu tiên để test).")

    if not pending_cases:
        print(f"✨ Toàn bộ {len(dataset)} câu hỏi đã được Leader phân loại xong từ trước!")
        return

    print(f"🔄 Đã phân loại {already_routed}/{len(dataset)} câu. Còn lại {len(pending_cases)} câu cần phân loại.")
    
    # Khởi tạo Coordinator Agent (Chỉ gọi API FPT Gemma)
    coordinator = CoordinatorAgent()
    sem = asyncio.Semaphore(20) # Gọi API Leader song song 20 worker

    async def process_route(tc):
        async with sem:
            query = tc["generation_ground_truth"]["user_query"]
            # Gọi hàm get_route để LLM phân tích câu hỏi thuộc chuyên môn nào
            agent_name = await coordinator.get_route(query)
            tc["assigned_agent"] = agent_name

    tasks = [process_route(tc) for tc in pending_cases]
    
    for i, f in enumerate(tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Routing Questions")):
        await f
        # Save liên tục sau mỗi 50 câu
        if (i + 1) % 50 == 0:
            with open(DATASET_FILE, "w", encoding="utf-8") as file:
                json.dump(dataset, file, ensure_ascii=False, indent=2)

    # Save lần cuối
    with open(DATASET_FILE, "w", encoding="utf-8") as file:
        json.dump(dataset, file, ensure_ascii=False, indent=2)

    print("\n✅ Đã hoàn thành dán nhãn chuyên môn cho toàn bộ Test Dataset!")
    print("Bây giờ bạn có thể chạy benchmark_nvidia_models.py để test thực tế!")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(route_all_questions())
