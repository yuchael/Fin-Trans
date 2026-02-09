import os
import pdfplumber
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import re

print("🚀 [최종] 금융 용어 PDF -> MySQL DB 적재 시작 (Strict Match Mode)...")

# 1. 환경변수 로드 (.env 파일)
load_dotenv()

DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "fintech_agent")

PDF_FILE_PATH = os.path.join(BASE_DIR, "..", "data", "economic_terms.pdf")

# 페이지 설정
INDEX_START_PAGE = 5   
INDEX_END_PAGE = 16    
BODY_START_PAGE = 17   

# 2. DB 연결 엔진 생성
def get_db_engine():
    # mysql+pymysql://사용자:비번@호스트:포트/DB명
    db_url = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    return create_engine(db_url)

# 3. 테이블 초기화 (기존 데이터 삭제 후 재생성)
def init_db_table():
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            # 기존 테이블이 있다면 삭제 (테스트용)
            conn.execute(text("DROP TABLE IF EXISTS terms"))
            
            # 테이블 생성 (definition은 긴 텍스트를 위해 LONGTEXT 사용)
            create_sql = """
            CREATE TABLE terms (
                id INT AUTO_INCREMENT PRIMARY KEY,
                word VARCHAR(255) NOT NULL,
                definition LONGTEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
            conn.execute(text(create_sql))
            print("✅ DB 테이블(terms) 초기화 완료.")
    except Exception as e:
        print(f"❌ DB 접속 또는 테이블 생성 오류: {e}")
        exit()

# 4. 정규화 함수 (비교용: 공백/특수문자 제거)
def normalize(text):
    if not text: return ""
    return re.sub(r'[\s\(\)\[\]\-\.,･・/]', '', text)

# 5. [1단계] 목차 정밀 추출 (노이즈 제거 + 합치기)
def extract_master_terms():
    print("📖 [1단계] 목차 정밀 추출 중...")
    term_list = []
    
    # 목차 패턴: "용어" + "점들" + "숫자"
    index_pattern = re.compile(r'^(?P<term>.*?)\s*[･・\.]+\s*\d+$')
    
    # 🔥 [수정] 15개 누락 원인이었던 헤더 노이즈 제거 패턴
    noise_prefix_pattern = re.compile(r'^(경제금융용어\s*\d*선|보기|참고)\s*')

    with pdfplumber.open(PDF_FILE_PATH) as pdf:
        for i in range(INDEX_START_PAGE - 1, INDEX_END_PAGE):
            page = pdf.pages[i]
            width = page.width
            height = page.height
            
            # 2단 분리
            left_box = (0, 60, width / 2, height - 50)
            right_box = (width / 2, 60, width, height - 50)
            
            for box in [left_box, right_box]:
                try:
                    text = page.crop(box).extract_text()
                except: continue
                if not text: continue
                
                lines = text.split('\n')
                prev_line = ""
                
                for line in lines:
                    # 기본 노이즈 제거
                    clean_line = line.replace("찾아보기", "").replace("찾아보", "").replace("❙", "").strip()
                    if not clean_line: continue
                    
                    # 🔥 헤더 노이즈 제거 (이게 있어야 '잠재GDP성장률' 등이 살아남음)
                    clean_line = noise_prefix_pattern.sub('', clean_line)

                    match = index_pattern.match(clean_line)
                    if match:
                        current_term = match.group('term').strip()
                        if prev_line:
                            # 줄바꿈 용어 합치기 (공백 없이)
                            full_term = f"{prev_line}{current_term}"
                            term_list.append(full_term)
                            prev_line = "" 
                        else:
                            if len(current_term) > 1:
                                term_list.append(current_term)
                    else:
                        if len(clean_line) > 1 and not clean_line.isdigit():
                            prev_line = clean_line

    # 중복 제거 (순서 유지 X -> set 후 리스트 변환)
    unique_terms = list(dict.fromkeys(term_list))
    print(f"✅ 목차 추출 완료: {len(unique_terms)}개 용어 기준 확보.")
    return unique_terms

# 6. [2단계] 본문 파싱 및 DB 적재
def parse_and_insert_db():
    # DB 초기화
    init_db_table()
    
    # 목차 가져오기
    master_terms = extract_master_terms()
    
    # 비교 속도를 위해 정규화된 셋(Set) 생성
    normalized_master_set = set(normalize(t) for t in master_terms)
    
    print(f"📂 [2단계] 본문 분석 및 DB 적재 시작 (엄격한 일치)...")
    
    data_list = [] # 대량 Insert를 위한 버퍼
    
    with pdfplumber.open(PDF_FILE_PATH) as pdf:
        current_title = ""
        current_body = ""
        
        for i, page in enumerate(pdf.pages):
            current_page_num = i + 1
            if current_page_num < BODY_START_PAGE: continue
            
            width, height = page.width, page.height
            try:
                # 본문 영역 크롭
                cropped = page.crop((0, 80, width, height - 70))
                text = cropped.extract_text()
            except: continue

            if not text: continue

            lines = text.split('\n')
            for line in lines:
                clean_line = line.strip()
                if len(clean_line) < 1: continue
                if "연관검색어" in clean_line: continue

                # 정규화
                norm_line = normalize(clean_line)
                
                # 🔥 [엄격한 로직] 정규화된 라인이 목차 셋에 '정확히' 있는가?
                # (포함 X, 일치 O) -> 문장 중간의 단어 때문에 끊기는 현상 방지
                is_title = norm_line in normalized_master_set

                if is_title:
                    # 이전 용어 저장 (리스트에 추가)
                    if current_title and current_body:
                        data_list.append({
                            "word": current_title,
                            "definition": current_body.strip()
                        })
                    
                    # 새 용어 시작
                    current_title = clean_line
                    current_body = "" # 제목 줄은 본문에 넣지 않음
                else:
                    # 본문 내용 추가
                    if "PDF.js" not in clean_line and not clean_line.isdigit():
                        current_body += " " + clean_line

            if current_page_num % 50 == 0:
                print(f"   ... {current_page_num}페이지 처리 중")

        # 마지막 용어 추가
        if current_title and current_body:
            data_list.append({
                "word": current_title,
                "definition": current_body.strip()
            })

    # DB에 일괄 저장 (Bulk Insert)
    if data_list:
        print(f"💾 총 {len(data_list)}개 데이터를 DB에 저장합니다...")
        df = pd.DataFrame(data_list)
        engine = get_db_engine()
        
        # pandas to_sql 사용 (빠르고 간편함)
        df.to_sql(name='terms', con=engine, if_exists='append', index=False)
        print("🎉 모든 작업 완료! 성공적으로 DB에 적재되었습니다.")
    else:
        print("⚠️ 저장할 데이터가 없습니다.")

if __name__ == "__main__":
    parse_and_insert_db()