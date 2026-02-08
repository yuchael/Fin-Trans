import requests
import os
import sys
import pandas as pd
import logging
import re
import io  # [필수] 문자열을 파일처럼 다루기 위해 필요
from datetime import datetime
from dotenv import load_dotenv

# utils 폴더의 handle_sql.py에서 함수 불러오기
try:
    from utils.handle_sql import execute_query, execute_many
except ImportError:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from utils.handle_sql import execute_query, execute_many

load_dotenv()

# --- [로깅 설정] ---
def setup_logging():
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "execution.log")

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode='w', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def fetch_naver_rates():
    """네이버 금융 환율 정보를 가져옵니다. (파일 저장 없이 메모리 처리)"""
    url = "https://finance.naver.com/marketindex/exchangeList.naver"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    logging.info("🔄 네이버 금융 데이터 요청 중...")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            # 1. 인코딩 설정 (네이버 금융은 cp949/euc-kr 사용)
            response.encoding = 'cp949'
            
            # 2. 데이터 파싱 (파일 저장 로직 제거됨)
            try:
                # [중요] response.text를 바로 read_html에 넣으면 파일 경로로 착각할 수 있어 io.StringIO 사용
                html_io = io.StringIO(response.text)
                
                # header=1: 두 번째 줄(사실 때, 파실 때 등)을 헤더로 인식 시도
                dfs = pd.read_html(html_io, header=1)
                
                if dfs:
                    df = dfs[0]
                    # 네이버 금융 환율표 구조 기반 인덱싱 (화면에 보이는 순서대로)
                    # col 0: 통화명
                    # col 1: 매매기준율
                    # col 4: 송금 보내실 때 (TTS)
                    # col 5: 송금 받으실 때 (TTB)
                    
                    # 필요한 컬럼만 위치(index)로 추출하여 복사
                    target_df = df.iloc[:, [0, 1, 4, 5]].copy()
                    
                    # 컬럼명 재설정 (DB 컬럼과 매핑하기 좋게 직관적으로 변경)
                    target_df.columns = ['통화명', '매매기준율', '전신환_보내실때', '전신환_받으실때']
                    
                    now = datetime.now()
                    date_str = now.strftime("%Y%m%d")
                    
                    logging.info(f"✅ 파싱 성공! 데이터 {len(target_df)}건을 찾았습니다.")
                    return target_df, date_str
                else:
                    logging.warning("⚠️ HTML 테이블을 찾을 수 없습니다.")
                    return None, None

            except ImportError:
                logging.error("❌ 'lxml' 라이브러리가 필요합니다. 터미널에 'pip install lxml'을 입력하세요.")
                return None, None
            except Exception as parse_error:
                logging.error(f"⚠️ 파싱 중 에러 발생: {parse_error}")
                return None, None
        else:
            logging.error(f"❌ 요청 실패 (Status: {response.status_code})")
            return None, None

    except Exception as e:
        logging.error(f"❌ 크롤링 에러: {e}")
        return None, None

def process_and_save(df, date_str):
    """데이터 전처리 및 저장 (CSV + MySQL)"""
    if df is None or df.empty:
        return

    # 전처리 작업을 위해 복사
    df = df.copy()

    # 1. 통화명 정제 (HTML의 공백/개행문자 제거)
    df['국가/통화명'] = df['통화명'].astype(str).str.strip()
    
    # 통화코드 추출 (예: "미국 USD" -> "USD", "일본 JPY (100엔)" -> "JPY")
    def extract_code(text):
        match = re.search(r'([A-Z]{3})', text)
        return match.group(1) if match else 'KRW'
    
    df['통화코드'] = df['국가/통화명'].apply(extract_code)

    # 2. 숫자 데이터 전처리 (콤마 제거, N/A 처리)
    target_cols = ['매매기준율', '전신환_보내실때', '전신환_받으실때']
    
    for col in target_cols:
        # 문자열 변환 -> 콤마 제거 -> 숫자로 변환 (실패시 NaN) -> NaN은 0으로 대체
        df[col] = df[col].astype(str).str.replace(",", "").str.strip()
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # 3. 기준일자 추가
    df['기준일자'] = date_str

    # 4. 저장할 컬럼 순서 정리
    final_columns = ['기준일자', '통화코드', '국가/통화명', '매매기준율', '전신환_받으실때', '전신환_보내실때']
    df = df[final_columns]

    # --- CSV 저장 ---
    save_dir = "data"
    os.makedirs(save_dir, exist_ok=True)
    csv_filename = os.path.join(save_dir, "exchange_rates.csv")
    df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
    logging.info(f"💾 CSV 저장 완료: {csv_filename}")
    
    # --- MySQL 저장 ---
    save_to_mysql(df, date_str)

def save_to_mysql(df, date_str):
    """MySQL 데이터베이스에 저장"""
    formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

    try:
        logging.info(f"🔌 MySQL 저장 시작 (기준일: {formatted_date})")
        
        # 1. 기존 데이터 삭제 (중복 방지)
        delete_sql = "DELETE FROM exchange_rates"
        execute_query(delete_sql, (formatted_date,))
        
        # 2. 새 데이터 삽입
        insert_sql = """
        INSERT INTO exchange_rates 
        (reference_date, currency_code, currency_name, deal_bas_r, ttb, tts)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        data_list = []
        for _, row in df.iterrows():
            data_list.append((
                formatted_date,
                row['통화코드'],
                row['국가/통화명'],
                row['매매기준율'],
                row['전신환_받으실때'],
                row['전신환_보내실때']
            ))
        
        inserted_count = execute_many(insert_sql, data_list)
        logging.info(f"📥 DB 저장 완료: {inserted_count}건")

    except Exception as e:
        logging.error(f"❌ DB 저장 오류: {e}")

if __name__ == "__main__":
    setup_logging()
    
    # SSL 경고 무시 (필요시 사용)
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    logging.info("🚀 환율 정보 업데이트 시작...")
    
    rates_data, rates_date = fetch_naver_rates()
    
    if rates_data is not None:
        process_and_save(rates_data, rates_date)
        logging.info("🎉 모든 작업이 성공적으로 완료되었습니다.")
    else:
        logging.warning("⚠️ 저장할 데이터가 없어 종료합니다.")