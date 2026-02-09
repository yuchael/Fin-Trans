import pdfplumber
import re
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_FILE_PATH = os.path.join(BASE_DIR, "data", "economic_terms.pdf")
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "final_verification_strict.txt")

# 페이지 설정
INDEX_START_PAGE = 5   
INDEX_END_PAGE = 16    
BODY_START_PAGE = 17   

# 정규화 함수: 띄어쓰기, 특수문자 무시하고 '글자'만 비교
def normalize(text):
    if not text: return ""
    return re.sub(r'[\s\(\)\[\]\-\.,･・/]', '', text)

# 1. 목차(Index) 추출 - "공백 없이 합치기" 로직
def extract_master_terms():
    print("📖 [1단계] 목차 정밀 추출 (기준점 확보)...")
    term_list = []
    # 목차 패턴: "용어" + "점들" + "숫자"
    index_pattern = re.compile(r'^(?P<term>.*?)\s*[･・\.]+\s*\d+$')

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
                    # 노이즈 제거
                    clean_line = line.replace("찾아보기", "").replace("찾아보", "").replace("❙", "").strip()
                    if not clean_line: continue

                    match = index_pattern.match(clean_line)
                    if match:
                        current_term = match.group('term').strip()
                        if prev_line:
                            # 줄바꿈된 용어는 붙여서 하나로 만듦
                            full_term = f"{prev_line}{current_term}"
                            term_list.append(full_term)
                            prev_line = "" 
                        else:
                            if len(current_term) > 1:
                                term_list.append(current_term)
                    else:
                        # 숫자로 끝나지 않는 줄 (용어의 앞부분)
                        if len(clean_line) > 1 and not clean_line.isdigit():
                            prev_line = clean_line

    # 중복 제거
    unique_terms = list(dict.fromkeys(term_list))
    print(f"✅ 목차 추출 완료: {len(unique_terms)}개 용어 기준")
    return unique_terms

# 2. 본문(Body) 검증 - "엄격한 일치(Strict Match)"
def verify_body_strict():
    master_terms = extract_master_terms()
    
    # 비교 속도를 위해 정규화된 셋(Set) 생성
    normalized_master_set = set(normalize(t) for t in master_terms)
    
    print(f"📖 [2단계] 본문 검증 및 파일 생성 ('{OUTPUT_FILE}')...")
    
    saved_count = 0
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
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

                    # 현재 라인 정규화
                    norm_line = normalize(clean_line)
                    
                    # 🔥 [엄격한 로직] 정규화된 라인이 목차 셋에 '정확히' 있는가?
                    is_title = norm_line in normalized_master_set

                    if is_title:
                        # 이전에 작업하던 용어 저장
                        if current_title and current_body:
                            f.write(f"[{current_title}]\n")
                            f.write(f"{current_body.strip()}\n")
                            f.write("-" * 50 + "\n")
                            saved_count += 1
                        
                        # 새 용어 시작
                        current_title = clean_line
                        current_body = "" # 제목 줄은 본문에 넣지 않음
                    else:
                        # 제목이 아니면 무조건 본문
                        if "PDF.js" not in clean_line and not clean_line.isdigit():
                            current_body += " " + clean_line

                if current_page_num % 50 == 0:
                    print(f"   ... {current_page_num}페이지")

            # 마지막 용어 저장
            if current_title and current_body:
                f.write(f"[{current_title}]\n")
                f.write(f"{current_body.strip()}\n")
                f.write("-" * 50 + "\n")
                saved_count += 1

    print(f"🎉 검증 완료! 총 {saved_count}개의 용어가 저장되었습니다.")
    print(f"👉 '{OUTPUT_FILE}' 파일을 확인하세요.")

if __name__ == "__main__":
    verify_body_strict()