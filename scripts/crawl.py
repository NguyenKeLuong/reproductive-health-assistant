"""
crawl.py
=========
Script tổng hợp (Unified Crawler) có chức năng thu thập dữ liệu từ nhiều nguồn khác nhau
nhằm xây dựng Cơ Sở Dữ Liệu Kiến Thức (Knowledge Base) cho Hệ thống Trợ lý Sức khỏe Sinh sản.

Thư mục đầu ra duy nhất: ./co_so_du_lieu_kien_thuc
Bên trong sẽ chia thành các thư mục tiếng Việt rõ ràng:
  - y_khoa_lam_sang        (Nguồn: MedlinePlus - API XML)
  - tam_ly_va_dong_thuan   (Nguồn: loveisrespect.org - Trafilatura)
  - thuc_hanh_tranh_thai   (Nguồn: bedsider.org - Trafilatura)
  - giao_duc_gioi_tinh     (Nguồn: kidshealth.org - Trafilatura)

Tất cả bài viết được gộp chung vào 1 file index duy nhất:
  ./co_so_du_lieu_kien_thuc/_index.json

Cách chạy:
    pip install requests beautifulsoup4 trafilatura lxml
    python crawl.py
"""

import json
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import trafilatura

# =====================================================================
# 1. CẤU HÌNH CHUNG & TIỆN ÍCH
# =====================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "knowledge_base"
REQUEST_DELAY_SEC = 1.0  # Thời gian chờ giữa các request (tránh bị block)
MAX_RETRIES = 3
TIMEOUT = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (ThesisResearchBot/1.0; educational use; TNU-ICTU student project)"
}

def slugify(text: str) -> str:
    """Chuyển tiêu đề thành tên file an toàn."""
    if not text:
        return "untitled"
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:80] or "untitled"

def safe_get(url: str, params: dict = None) -> requests.Response | None:
    """Hàm GET an toàn, có tự động thử lại (retry) khi gặp lỗi."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            print(f"    [!] Lỗi lần {attempt}/{MAX_RETRIES} khi GET {url}: {e}")
            time.sleep(2 * attempt)
    return None


# =====================================================================
# 2. MODULE CRAWL TỪ MEDLINEPLUS (Y Khoa Lâm Sàng - XML API)
# =====================================================================

MEDLINE_BASE_URL = "https://wsearch.nlm.nih.gov/ws/query"
MEDLINE_RETMAX = 200  # Đẩy lên mức tối đa 200 bài/từ khóa để vét sạch mọi ngóc ngách của thư viện y khoa

# Các từ khóa tra cứu y khoa (Bao phủ Toàn diện Sức khỏe sinh sản & Bệnh lý)
MEDLINE_KEYWORDS = {
    "SucKhoeTongQuatVaDayThi": [
        "puberty", "human body", "female reproductive system", "male reproductive system", 
        "personal hygiene", "body image", "anatomy", "wet dreams", "menarche", 
        "adolescent development", "masturbation", "sexual orientation", "gender identity",
        "safe sex", "sexual health"
    ],
    "BenhLayQuaDuongTinhDuc_STIs": [
        "HIV AIDS", "gonorrhea", "syphilis", "genital warts HPV",
        "hepatitis B", "hepatitis C", "chlamydia", "genital herpes",
        "trichomoniasis", "mycoplasma genitalium", "chancroid", 
        "pubic lice crabs", "scabies", "sexually transmitted diseases",
        "STD testing", "PrEP HIV prevention", "PEP HIV", "preventing STIs"
    ],
    "ViemNhiemVaPhuKhoa": [
        "pelvic inflammatory disease", "bacterial vaginosis", "vaginal yeast infection",
        "vaginitis", "endometriosis", "uterine fibroids", "ovarian cysts", 
        "cervical cancer", "ovarian cancer", "polycystic ovary syndrome",
        "toxic shock syndrome", "vulvodynia"
    ],
    "NamKhoaVaBenhLy": [
        "testicular pain", "jock itch", "prostate health", "erectile dysfunction",
        "premature ejaculation", "balanitis", "epididymitis", "varicocele",
        "peyronie disease", "male infertility", "testicular cancer", "prostate cancer"
    ],
    "TranhThaiVaKeHoachHoaGiaDinh": [
        "birth control pills", "IUD", "birth control implant",
        "emergency contraception", "birth control methods",
        "male condoms", "female condoms", "contraceptive patch", "vaginal ring",
        "spermicide", "tubal ligation", "vasectomy", "birth control side effects"
    ],
    "SinhSanVaThaiKy": [
        "fertility", "infertility", "ovulation", "pregnancy planning", 
        "prenatal care", "miscarriage", "ectopic pregnancy", 
        "postpartum depression", "menopause", "perimenopause"
    ],
    "TamLyAnToanDongThuan": [
        "sexual abuse", "domestic violence", "dating violence",
        "healthy relationships", "consent", "sexual assault",
        "crisis hotlines", "child abuse prevention", "peer pressure"
    ],
}

def parse_medline_document(doc: ET.Element) -> dict:
    """Xử lý 1 thẻ <document> XML của MedlinePlus thành dict."""
    item = {
        "url": doc.get("url"),
        "title": None,
        "full_summary": None,
        "also_called": [],
        "mesh_headings": [],
        "groups": [],
        "organization": None,
    }
    for content in doc.findall("content"):
        name = content.get("name")
        text = "".join(content.itertext()).strip()
        
        # Loại bỏ các thẻ HTML rác và thẻ highlight
        clean_text = re.sub(r'<[^>]+>', ' ', text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()

        if name == "title":
            item["title"] = clean_text
        elif name == "FullSummary":
            item["full_summary"] = clean_text
        elif name == "altTitle":
            item["also_called"].append(clean_text)
        elif name == "mesh":
            item["mesh_headings"].append(clean_text)
        elif name == "groupName":
            item["groups"].append(clean_text)
        elif name == "organizationName":
            item["organization"] = clean_text

    return item

def crawl_medlineplus() -> list[dict]:
    """Crawl toàn bộ dữ liệu từ API của MedlinePlus."""
    out_dir = OUTPUT_DIR / "y_khoa_lam_sang"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n=======================================================")
    print("BẮT ĐẦU CRAWL: MEDLINEPLUS (Y Khoa Lâm Sàng)")
    print("=======================================================")
    
    index_data = []
    seen_urls = set()

    for sub_cat, keywords in MEDLINE_KEYWORDS.items():
        print(f"\n--- Nhóm: {sub_cat} ---")
        for kw in keywords:
            print(f"  -> Đang tra cứu: '{kw}'")
            params = {"db": "healthTopics", "term": kw, "retmax": MEDLINE_RETMAX}
            resp = safe_get(MEDLINE_BASE_URL, params=params)
            time.sleep(REQUEST_DELAY_SEC)

            if not resp:
                continue

            try:
                root = ET.fromstring(resp.content)
            except ET.ParseError:
                continue

            documents = root.findall(".//document")
            for doc in documents:
                parsed = parse_medline_document(doc)
                url = parsed["url"]

                if not parsed["title"] or url in seen_urls:
                    continue
                seen_urls.add(url)

                # Xác định Agent chịu trách nhiệm dựa trên nhóm
                target_agents = []
                if sub_cat == "SucKhoeTongQuatVaDayThi": target_agents = ["GeneralHealthAgent"]
                elif sub_cat == "BenhLayQuaDuongTinhDuc_STIs": target_agents = ["STIAgent"]
                elif sub_cat == "TranhThaiVaKeHoachHoaGiaDinh": target_agents = ["ContraceptionAgent"]
                elif sub_cat == "SucKhoeSinhSanVaPhuKhoa": target_agents = ["ReproductiveHealthAgent"]
                elif sub_cat == "NamKhoaVaBenhLy": target_agents = ["ReproductiveHealthAgent"]
                elif sub_cat == "ViemNhiemVaPhuKhoa": target_agents = ["ReproductiveHealthAgent", "STIAgent"]
                elif sub_cat == "SinhSanVaThaiKy": target_agents = ["ReproductiveHealthAgent"]
                elif sub_cat == "TamLyAnToanDongThuan": target_agents = ["SafetyConsentAgent"]

                parsed["source"] = "MedlinePlus"
                parsed["target_agent"] = target_agents

                filename = f"{slugify(parsed['title'])}.json"
                filepath = out_dir / filename

                if filepath.exists():
                    print(f"    [SKIPPED - EXISTED] {parsed['title']}")
                    index_data.append({
                        "source": "MedlinePlus",
                        "category": "y_khoa_lam_sang",
                        "title": parsed["title"],
                        "url": url,
                        "target_agent": target_agents,
                        "file": str(filepath.relative_to(OUTPUT_DIR)),
                    })
                    continue

                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(parsed, f, ensure_ascii=False, indent=2)

                index_data.append({
                    "source": "MedlinePlus",
                    "category": "y_khoa_lam_sang",
                    "title": parsed["title"],
                    "url": url,
                    "target_agent": target_agents,
                    "file": str(filepath.relative_to(OUTPUT_DIR)),
                })
                print(f"    [OK] {parsed['title']}")

    return index_data


# =====================================================================
# 3. MODULE CRAWL EXTERNAL SITES (Tâm lý, Tránh thai, Giáo dục giới tính)
# =====================================================================

EXTERNAL_SOURCES = {
    "loveisrespect": {
        "folder": "tam_ly_va_dong_thuan",
        "base_url": "https://www.loveisrespect.org",
        "seed_pages": [
            "https://www.loveisrespect.org/dating-basics-for-healthy-relationships/",
            "https://www.loveisrespect.org/everyone-deserves-a-healthy-relationship/",
            "https://www.loveisrespect.org/personal-safety/",
            "https://www.loveisrespect.org/supporting-others-dating-abuse/",
            "https://www.loveisrespect.org/get-relationship-help-24-7-365/",
            "https://www.loveisrespect.org/search-our-resources/",
        ],
        "link_pattern": re.compile(
            r'href="([^"?#]*?(?:resources|'
            r'dating-basics-for-healthy-relationships|'
            r'everyone-deserves-a-healthy-relationship|'
            r'personal-safety|'
            r'supporting-others-dating-abuse|'
            r'get-relationship-help-24-7-365)/[^"?#]+)"'
        ),
        "target_agent": ["SafetyConsentAgent"],
    },
    "bedsider": {
        "folder": "thuc_hanh_tranh_thai",
        "base_url": "https://www.bedsider.org",
        "fixed_urls": [
            "https://www.bedsider.org/birth-control/iud",
            "https://www.bedsider.org/birth-control/iud_hormonal",
            "https://www.bedsider.org/birth-control/iud_non_hormonal",
            "https://www.bedsider.org/birth-control/implant",
            "https://www.bedsider.org/birth-control/the_shot",
            "https://www.bedsider.org/birth-control/in_office_birth_control_shot",
            "https://www.bedsider.org/birth-control/at_home_birth_control_shot",
            "https://www.bedsider.org/birth-control/the_ring",
            "https://www.bedsider.org/birth-control/the_ring_yearly",
            "https://www.bedsider.org/birth-control/the_ring_monthly",
            "https://www.bedsider.org/birth-control/the_patch",
            "https://www.bedsider.org/birth-control/the_pill",
            "https://www.bedsider.org/birth-control/the_pill_progestin_only",
            "https://www.bedsider.org/birth-control/the_pill_combo",
            "https://www.bedsider.org/birth-control/diaphragm",
            "https://www.bedsider.org/birth-control/condom",
            "https://www.bedsider.org/birth-control/internal_condom",
            "https://www.bedsider.org/birth-control/cervical_cap",
            "https://www.bedsider.org/birth-control/fertility_awareness",
            "https://www.bedsider.org/birth-control/spermicide",
            "https://www.bedsider.org/birth-control/prescription_only_spermicide_phexxi",
            "https://www.bedsider.org/birth-control/over_the_counter_spermicide",
            "https://www.bedsider.org/birth-control/withdrawal",
            "https://www.bedsider.org/birth-control/sterilization",
            "https://www.bedsider.org/birth-control/tubal_ligation",
            "https://www.bedsider.org/birth-control/vasectomy",
            "https://www.bedsider.org/birth-control/not_right_now",
            "https://www.bedsider.org/birth-control/emergency_contraception",
            "https://www.bedsider.org/birth-control/over_the_counter_ec",
            "https://www.bedsider.org/birth-control/ec_ella_pill",
            "https://www.bedsider.org/birth-control/ec_iud",
        ],
        "seed_pages": [
            "https://www.bedsider.org/sex-and-relationships/boundaries-and-consent",
            "https://www.bedsider.org/sex-and-relationships",
            "https://www.bedsider.org/sexual-health-and-wellness/sexually-transmitted-infections-stds-stis",
            "https://www.bedsider.org/sexual-health-and-wellness",
            "https://www.bedsider.org/lifestyle-and-inspiration/self-love-and-body-positivity",
            "https://www.bedsider.org/features/tagged/birth_control",
        ],
        "link_pattern": re.compile(
            r'href="([^"?#]*?/(?:birth-control|sex-and-relationships|'
            r'sexual-health-and-wellness|lifestyle-and-inspiration|'
            r'features)/[^"?#]+)"'
        ),
        "target_agent": ["ContraceptionAgent", "STIAgent"],
    },
    "kidshealth": {
        "folder": "giao_duc_gioi_tinh",
        "base_url": "https://kidshealth.org",
        "seed_pages": [
            "https://kidshealth.org/en/teens/sexual-health/",
            "https://kidshealth.org/en/teens/diseases-conditions/sexual-health/",
            "https://kidshealth.org/en/teens/your-body/",
        ],
        "link_pattern": re.compile(r'href="([^"?#]*?/en/teens/[^"?#]+\.html)"'),
        "target_agent": ["GeneralHealthAgent", "ReproductiveHealthAgent"],
    },
    "plannedparenthood": {
        "folder": "tong_hop_sinh_san",
        "base_url": "https://www.plannedparenthood.org",
        "seed_pages": [
            "https://www.plannedparenthood.org/learn/birth-control",
            "https://www.plannedparenthood.org/learn/stds-hiv-safer-sex",
            "https://www.plannedparenthood.org/learn/pregnancy",
            "https://www.plannedparenthood.org/learn/teens",
            "https://www.plannedparenthood.org/learn/health-and-wellness",
            "https://www.plannedparenthood.org/learn/gender-identity"
        ],
        "link_pattern": re.compile(r'href="(/learn/(?:birth-control|stds-hiv-safer-sex|pregnancy|teens|health-and-wellness|gender-identity|sexual-orientation-gender)/[^"?#]+)"'),
        "target_agent": ["ReproductiveHealthAgent", "ContraceptionAgent", "STIAgent"],
    },
    "scarleteen": {
        "folder": "giao_duc_gioi_tinh",
        "base_url": "https://www.scarleteen.com",
        "seed_pages": [
            "https://www.scarleteen.com/read/bodies",
            "https://www.scarleteen.com/read/sex-sexuality",
            "https://www.scarleteen.com/read/pregnancy-reproduction",
            "https://www.scarleteen.com/read/relationships",
            "https://www.scarleteen.com/read/sexual-health"
        ],
        "link_pattern": re.compile(r'href="(/read/(?:bodies|sex-sexuality|pregnancy-reproduction|relationships|sexual-health)/[^"?#]+)"'),
        "target_agent": ["GeneralHealthAgent", "SafetyConsentAgent"],
    },
    "nhs_uk": {
        "folder": "y_khoa_lam_sang",
        "base_url": "https://www.nhs.uk",
        "seed_pages": [
            "https://www.nhs.uk/contraception/",
            "https://www.nhs.uk/pregnancy/",
            "https://www.nhs.uk/conditions/sexually-transmitted-infections-stis/"
        ],
        "link_pattern": re.compile(r'href="(https://www\.nhs\.uk/(?:contraception|pregnancy|conditions/sexually-transmitted-infections-stis)/[^"?#]+)"'),
        "target_agent": ["ReproductiveHealthAgent", "ContraceptionAgent", "STIAgent"],
    },
}

def discover_external_urls(source_name: str, cfg: dict) -> list[str]:
    """Tìm tất cả các bài viết của nguồn."""
    found = set(cfg.get("fixed_urls", []))
    for seed in cfg["seed_pages"]:
        print(f"    -> Quét seed: {seed}")
        resp = safe_get(seed)
        time.sleep(REQUEST_DELAY_SEC)
        if not resp:
            continue
        matches = cfg["link_pattern"].findall(resp.text)
        for m in matches:
            full_url = urljoin(cfg["base_url"], m)
            found.add(full_url.rstrip("/"))
    print(f"    -> Tìm được {len(found)} URL cho {source_name}")
    # Không giới hạn số lượng bài viết để lấy cạn kiệt dữ liệu của từng trang
    return list(found)

def extract_article(url: str) -> dict | None:
    """Dùng trafilatura lấy text sạch từ HTML."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        downloaded = r.text
    except Exception as e:
        print(f"    [!] Lỗi fetch {url}: {e}")
        return None

    if not downloaded:
        return None

    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    metadata = trafilatura.extract_metadata(downloaded)

    if not text or len(text.strip()) < 200:
        return None

    return {
        "url": url,
        "title": metadata.title if metadata else None,
        "text": text.strip(),
        "author": metadata.author if metadata else None,
        "date": metadata.date if metadata else None,
        "description": metadata.description if metadata else None,
    }

def crawl_external_sources() -> list[dict]:
    """Crawl dữ liệu từ các trang ngoài (HTML Web)."""
    index_data = []

    for source_name, cfg in EXTERNAL_SOURCES.items():
        print(f"\n=======================================================")
        print(f"BẮT ĐẦU CRAWL: {source_name.upper()} ({cfg['folder']})")
        print("=======================================================")
        
        out_dir = OUTPUT_DIR / cfg["folder"]
        out_dir.mkdir(parents=True, exist_ok=True)

        urls = discover_external_urls(source_name, cfg)
        if not urls:
            continue

        for i, url in enumerate(urls, 1):
            print(f"  [{i}/{len(urls)}] {url}")
            
            # Đặt tên file dựa trên URL để có tính xác định (deterministic)
            filename = f"{slugify(urlparse(url).path)}.json"
            if not filename or filename == ".json" or filename == "untitled.json":
                # Fallback to hash if path is empty
                filename = f"{hash(url)}.json"
                
            filepath = out_dir / filename

            if filepath.exists():
                print(f"    [SKIPPED - EXISTED] {url}")
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        cached_article = json.load(f)
                    index_data.append({
                        "source": source_name,
                        "category": cfg["folder"],
                        "title": cached_article.get("title", "Untitled"),
                        "url": url,
                        "target_agent": cfg.get("target_agent", []),
                        "file": str(filepath.relative_to(OUTPUT_DIR)),
                    })
                except Exception:
                    pass
                continue

            try:
                article = extract_article(url)
            except Exception as e:
                print(f"    [!] Lỗi extract: {e}")
                time.sleep(REQUEST_DELAY_SEC)
                continue

            time.sleep(REQUEST_DELAY_SEC)

            if not article:
                continue

            article["source"] = source_name
            article["target_agent"] = cfg["target_agent"]

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(article, f, ensure_ascii=False, indent=2)

            index_data.append({
                "source": source_name,
                "category": cfg["folder"],
                "title": article["title"],
                "url": url,
                "target_agent": cfg["target_agent"],
                "file": str(filepath.relative_to(OUTPUT_DIR)),
            })

    return index_data


# =====================================================================
# 4. HÀM CHẠY CHÍNH (MAIN)
# =====================================================================

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    master_index = []

    # 1. Crawl MedlinePlus
    medline_index = crawl_medlineplus()
    master_index.extend(medline_index)
    # 2. Crawl External Sources (Tắt để chống trùng lặp theo yêu cầu)
    # external_index = crawl_external_sources()
    # master_index.extend(external_index)

    # 3. Ghi file Index tổng hợp
    index_path = OUTPUT_DIR / "_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(master_index, f, ensure_ascii=False, indent=2)

    print("\n=======================================================")
    print("HOÀN TẤT TOÀN BỘ QUÁ TRÌNH CRAWL")
    print(f"Tổng số bài viết đã lưu: {len(master_index)}")
    print(f"Index tổng hợp lưu tại: {index_path.resolve()}")
    print("=======================================================")

if __name__ == "__main__":
    main()