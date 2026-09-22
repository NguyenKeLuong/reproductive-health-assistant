import json
import os
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

# ===============================
# Config & Smart Path Resolution
# ===============================
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Search candidate locations for the embedded knowledge base file
CANDIDATE_PATHS = [
    PROJECT_ROOT / "data" / "embeddings" / "knowledge_base_embedded.json",
    PROJECT_ROOT / "knowledge_base_embedded.json",
    Path("knowledge_base_embedded.json"),
]

KB_EMBEDDED_FILE = next((p for p in CANDIDATE_PATHS if p.exists()), CANDIDATE_PATHS[0])
COLLECTION_NAME = "reproductive_health_kb"
QDRANT_STORAGE_PATH = str(PROJECT_ROOT / "qdrant_data")

def setup_qdrant():
    print(f"Đang đọc dữ liệu từ: {KB_EMBEDDED_FILE}...")
    if not KB_EMBEDDED_FILE.exists():
        print(f"LỖI: Không tìm thấy file {KB_EMBEDDED_FILE}.")
        print("Vui lòng đặt file tại: data/embeddings/knowledge_base_embedded.json")
        return

    with open(KB_EMBEDDED_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        print("File rỗng!")
        return

    # Khởi tạo Qdrant Local
    print(f"Lưu trữ cơ sở dữ liệu Qdrant tại: {QDRANT_STORAGE_PATH}")
    client = QdrantClient(path=QDRANT_STORAGE_PATH)

    # Xác định chiều của Vector (Dimension) dựa vào vector đầu tiên
    vector_size = len(data[0]["embedding"])
    print(f"Phát hiện Vector Dimension: {vector_size}")

    # Xóa collection cũ nếu tồn tại và tạo mới
    if client.collection_exists(COLLECTION_NAME):
        print(f"Collection '{COLLECTION_NAME}' đã tồn tại, tiến hành xóa và tạo lại...")
        client.delete_collection(COLLECTION_NAME)

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )

    print("Bắt đầu nạp dữ liệu vào Qdrant...")
    points = []
    for idx, item in enumerate(data):
        point = PointStruct(
            id=idx,
            vector=item["embedding"],
            payload={
                "chunk_id": item["chunk_id"],
                "source_file": item["source_file"],
                "category": item["category"],
                "text": item["text"]
            }
        )
        points.append(point)

    # Nạp vào DB theo lô (upload_points tự động xử lý batch)
    client.upload_points(
        collection_name=COLLECTION_NAME,
        points=points
    )

    print(f"THÀNH CÔNG! Đã nạp {len(points)} bài viết vào Qdrant Database.")

if __name__ == "__main__":
    setup_qdrant()
