import os
import json
import glob
from tqdm import tqdm
from sentence_transformers import SentenceTransformer

# ==========================
# Config
# ==========================
LOCAL_MODE = False # Đổi thành False khi bạn đẩy code này lên Kaggle

# Sử dụng mô hình của bạn (Context length cực lớn, nhúng nguyên bài không bị cắt gọt)
MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

if LOCAL_MODE:
    KB_DIR = str(PROJECT_ROOT / "data" / "knowledge_base")
    TEST_FILE = str(PROJECT_ROOT / "data" / "datasets" / "rag_test_dataset_1000.json")
    OUTPUT_KB_FILE = str(PROJECT_ROOT / "data" / "embeddings" / "knowledge_base_embedded.json")
    OUTPUT_TEST_FILE = str(PROJECT_ROOT / "data" / "datasets" / "rag_test_dataset_embedded.json")
else:
    KB_DIR = "/kaggle/input/datasets/nlgluong/chatsinhsan-dataset/co_so_du_lieu_kien_thuc"
    TEST_FILE = "/kaggle/input/datasets/nlgluong/chatsinhsan-dataset/rag_test_dataset_1000.json"
    OUTPUT_KB_FILE = "/kaggle/working/knowledge_base_embedded.json"
    OUTPUT_TEST_FILE = "/kaggle/working/rag_test_dataset_embedded.json"

BATCH_SIZE = 1 # Giảm xuống 1 vì Kaggle T4 GPU 15GB không chịu nổi ma trận Attention của bài quá dài

# ==========================
# 1. Nhúng Vector cho Cơ sở dữ liệu (Database)
import torch
# ==========================
print(f"Loading Embedding Model: {MODEL_NAME} in FP16")
# SOTA Strategy 3: Sử dụng Half-Precision (FP16) để giảm một nửa dung lượng RAM/VRAM
# Thay vì cắt cụt bài báo, ta bắt PyTorch chạy ở chế độ 16-bit. 
# Model 9.5GB sẽ co lại còn ~4.5GB. Ma trận 7.3GB sẽ co lại còn ~3.6GB.
# Đủ sức nhét trọn vẹn bài viết 6.500 từ vào GPU 15GB của Kaggle!
model = SentenceTransformer(
    MODEL_NAME, 
    device='cuda', 
    model_kwargs={"torch_dtype": torch.float16}
)

print(f"\n--- BẮT ĐẦU XỬ LÝ KNOWLEDGE BASE ---")
all_chunks = []
# Quét toàn bộ file json trong thư mục
json_files = glob.glob(f"{KB_DIR}/**/*.json", recursive=True)
json_files = [f for f in json_files if "_index.json" not in f]

print(f"Tìm thấy {len(json_files)} bài viết. Đang chuẩn bị dữ liệu...")
for file_path in json_files:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        text = data.get("text", "") or data.get("full_summary", "")
        if not text:
            continue
            
        category = os.path.basename(os.path.dirname(file_path))
        file_id = os.path.basename(file_path)
        # SOTA Strategy 1: Metadata Injection (Bơm siêu dữ liệu)
        # Bơm thêm Category và Tên file vào đầu văn bản để mô hình có "Neo ngữ nghĩa" (Semantic Anchor)
        # Rất hữu ích khi Query là tiếng Việt mà Text là tiếng Anh
        enriched_text = f"Category: {category}\nTitle: {file_id.replace('.json', '')}\n\n{text}"
        
        all_chunks.append({
            "chunk_id": file_id,
            "source_file": file_id,
            "category": category,
            "text": text, # Vẫn lưu text gốc để RAG trả về
            "passage_for_embedding": enriched_text # Nhưng nhúng text đã được bơm metadata
        })
    except Exception as e:
        print(f"Lỗi đọc file {file_path}: {e}")

print(f"Tổng số bài viết để nhúng: {len(all_chunks)}. Bắt đầu nhúng Vector...")

import torch
import gc

# Nhúng thủ công từng batch để dọn dẹp RAM/VRAM
texts_to_embed = [item["passage_for_embedding"] for item in all_chunks]
all_embeddings = []

for i in tqdm(range(0, len(texts_to_embed), BATCH_SIZE), desc="Embedding Batches"):
    batch_texts = texts_to_embed[i:i + BATCH_SIZE]
    
    # Encode batch hiện tại
    batch_emb = model.encode(batch_texts, show_progress_bar=False, normalize_embeddings=True)
    all_embeddings.extend(batch_emb.tolist())
    
    # Giải phóng VRAM ngay lập tức sau mỗi batch
    del batch_emb
    gc.collect()
    torch.cuda.empty_cache()

# Lưu vector vào list
for i, item in enumerate(all_chunks):
    item["embedding"] = all_embeddings[i]
    del item["passage_for_embedding"] # Xóa cho nhẹ file

with open(OUTPUT_KB_FILE, "w", encoding="utf-8") as f:
    json.dump(all_chunks, f, ensure_ascii=False)
print(f"Đã lưu Database Embeddings tại: {OUTPUT_KB_FILE}")

# ==========================
# 2. Nhúng Vector cho Tập Test (Query)
# ==========================
print(f"\n--- BẮT ĐẦU XỬ LÝ TEST DATASET ---")
try:
    with open(TEST_FILE, "r", encoding="utf-8") as f:
        test_cases = json.load(f)
        
    print(f"Load thành công {len(test_cases)} câu hỏi test.")
    
    # SOTA Strategy 2: Task-Specific Instruction (Nếu mô hình hỗ trợ)
    # Một số mô hình (như BGE, Qwen, E5) hoạt động cực tốt nếu Query được gán thêm ngữ cảnh truy vấn
    # Ví dụ: "Dưới đây là một câu hỏi y khoa tiếng Việt, hãy tìm bài viết tiếng Anh tương ứng: "
    # Tạm thời ta chỉ dùng Query gốc, nhưng nếu mô hình Qwen của bạn là bản Instruct, hãy bật dòng dưới:
    # queries = [f"Given a medical question in Vietnamese, retrieve the relevant English document: {tc['generation_ground_truth']['user_query']}" for tc in test_cases]
    queries = [tc['generation_ground_truth']['user_query'] for tc in test_cases]
    
    print("Đang nhúng Vector cho các câu hỏi...")
    
    # Đối với câu hỏi thì ngắn, có thể dùng Batch Size lớn hơn nhưng để an toàn cứ dùng vòng lặp dọn dẹp
    query_embeddings = []
    for i in tqdm(range(0, len(queries), BATCH_SIZE * 8), desc="Embedding Queries"):
        batch_q = queries[i:i + BATCH_SIZE * 8]
        batch_emb = model.encode(batch_q, show_progress_bar=False, normalize_embeddings=True)
        query_embeddings.extend(batch_emb.tolist())
        
        del batch_emb
        gc.collect()
        torch.cuda.empty_cache()
    
    for i, tc in enumerate(test_cases):
        tc["user_query_embedding"] = query_embeddings[i]
        
    with open(OUTPUT_TEST_FILE, "w", encoding="utf-8") as f:
        json.dump(test_cases, f, ensure_ascii=False, indent=2)
    print(f"Đã lưu Test Dataset Embeddings tại: {OUTPUT_TEST_FILE}")

except Exception as e:
    print(f"Lỗi xử lý file Test: {e}")

print("\nHOÀN TẤT TẤT CẢ! BẠN CÓ THỂ TẢI 2 FILE NÀY TỪ KAGGLE VỀ.")