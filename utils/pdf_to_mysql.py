import os
import pdfplumber
import re
import pandas as pd
from dotenv import load_dotenv


from utils.handle_sql import execute_query, execute_many

print("🚀 [최종] 금융 용어 PDF -> MySQL DB 적재 시작 (Strict Match Mode)...")

# 1. 환경변수 로드
load_dotenv()

# 파일 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # 현재 파일 위치 기준
PDF_FILE_PATH = os.path.join(BASE_DIR, "..", "data", "economic_terms.pdf")

# 페이지 설정
INDEX_START_PAGE = 5   
INDEX_END_PAGE = 16    
BODY_START_PAGE = 17   

# 3. 테이블 초기화 (기존 데이터 삭제 후 재생성)
def init_db_table():
    try:
        print("⚙️ DB 테이블(terms) 초기화 중...")
        # [변경] execute_query를 사용하여 DDL 실행
        execute_query("DROP TABLE IF EXISTS terms")
        
        create_sql = """
        CREATE TABLE terms (
            id INT AUTO_INCREMENT PRIMARY KEY,
            word VARCHAR(255) NOT NULL,
            definition LONGTEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        execute_query(create_sql)
        print("✅ DB 테이블(terms) 초기화 완료.")
    except Exception as e:
        print(f"❌ DB 초기화 오류: {e}")
        exit()

# 4. 정규화 함수 (비교용: 공백/특수문자 제거)
def normalize(text):
    if not text: return ""
    return re.sub(r'[\s\(\)\[\]\-\.,･・/]', '', text)

# 5. [1단계] 목차 정밀 추출 (노이즈 제거 + 합치기)
def extract_master_terms():
    print("📖 [1단계] 목차 정밀 추출 중...")
    term_list = []
    
    index_pattern = re.compile(r'^(?P<term>.*?)\s*[･・\.]+\s*\d+$')
    noise_prefix_pattern = re.compile(r'^(경제금융용어\s*\d*선|보기|참고)\s*')

    with pdfplumber.open(PDF_FILE_PATH) as pdf:
        for i in range(INDEX_START_PAGE - 1, INDEX_END_PAGE):
            page = pdf.pages[i]
            width = page.width
            height = page.height
            
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
                    clean_line = line.replace("찾아보기", "").replace("찾아보", "").replace("❙", "").strip()
                    if not clean_line: continue
                    
                    clean_line = noise_prefix_pattern.sub('', clean_line)

                    match = index_pattern.match(clean_line)
                    if match:
                        current_term = match.group('term').strip()
                        if prev_line:
                            full_term = f"{prev_line}{current_term}"
                            term_list.append(full_term)
                            prev_line = "" 
                        else:
                            if len(current_term) > 1:
                                term_list.append(current_term)
                    else:
                        if len(clean_line) > 1 and not clean_line.isdigit():
                            prev_line = clean_line

    unique_terms = list(dict.fromkeys(term_list))
    print(f"✅ 목차 추출 완료: {len(unique_terms)}개 용어 기준 확보.")
    return unique_terms

# 6. [2단계] 본문 파싱 및 DB 적재
def parse_and_insert_db():
    # DB 초기화
    init_db_table()
    
    master_terms = extract_master_terms()
    normalized_master_set = set(normalize(t) for t in master_terms)
    
    print(f"📂 [2단계] 본문 분석 및 DB 적재 시작 (엄격한 일치)...")
    
    data_list = [] 
    
    with pdfplumber.open(PDF_FILE_PATH) as pdf:
        current_title = ""
        current_body = ""
        
        for i, page in enumerate(pdf.pages):
            current_page_num = i + 1
            if current_page_num < BODY_START_PAGE: continue
            
            width, height = page.width, page.height
            try:
                cropped = page.crop((0, 80, width, height - 70))
                text = cropped.extract_text()
            except: continue

            if not text: continue

            lines = text.split('\n')
            for line in lines:
                clean_line = line.strip()
                if len(clean_line) < 1: continue
                if "연관검색어" in clean_line: continue

                norm_line = normalize(clean_line)
                is_title = norm_line in normalized_master_set

                if is_title:
                    if current_title and current_body:
                        # 튜플 형태로 저장 (execute_many 사용을 위해)
                        data_list.append((current_title, current_body.strip()))
                    
                    current_title = clean_line
                    current_body = "" 
                else:
                    if "PDF.js" not in clean_line and not clean_line.isdigit():
                        current_body += " " + clean_line

            if current_page_num % 50 == 0:
                print(f"   ... {current_page_num}페이지 처리 중")

        if current_title and current_body:
            data_list.append((current_title, current_body.strip()))

    # DB에 일괄 저장 (Bulk Insert)
    if data_list:
        print(f"💾 총 {len(data_list)}개 데이터를 DB에 저장합니다...")
        
        # [변경] execute_many를 사용하여 대량 삽입
        insert_sql = "INSERT INTO terms (word, definition) VALUES (%s, %s)"
        try:
            count = execute_many(insert_sql, data_list)
            print(f"🎉 성공적으로 {count}개의 데이터가 DB에 적재되었습니다.")
        except Exception as e:
            print(f"❌ 데이터 적재 중 오류 발생: {e}")
    else:
        print("⚠️ 저장할 데이터가 없습니다.")

if __name__ == "__main__":
    parse_and_insert_db()