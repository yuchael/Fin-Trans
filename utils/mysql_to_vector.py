import os
import json
import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm

from utils.handle_sql import get_data, execute_query

print("🚀 [Embedding] 데이터 벡터화 및 DB 저장 시작...")

# 1. 환경설정
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# 2. 임베딩 컬럼 추가 (없을 경우)
def add_embedding_column():
    try:
        # [변경] execute_query를 사용하여 DDL 실행
        # MySQL 5.7+ JSON 타입 지원
        execute_query("ALTER TABLE terms ADD COLUMN embedding JSON")
        print("✅ 'embedding' 컬럼이 생성되었습니다.")
    except Exception as e:
        # 이미 컬럼이 존재하는 경우 (오류 메시지로 판별)
        if "Duplicate column" in str(e) or "1060" in str(e):
            print("ℹ️ 'embedding' 컬럼이 이미 존재합니다.")
        else:
            print(f"⚠️ 컬럼 추가 중 경고: {e}")

# 3. 임베딩 생성 함수 (OpenAI API)
def get_embedding(text, model="text-embedding-3-small"):
    text = text.replace("\n", " ")  # 줄바꿈 제거
    return client.embeddings.create(input=[text], model=model).data[0].embedding

# 4. 메인 로직
def generate_and_save_embeddings():
    # 1) 아직 임베딩이 없는 데이터만 조회
    # [변경] get_data를 사용하여 딕셔너리 리스트로 가져옴
    print("📦 임베딩 대상 데이터를 조회합니다...")
    rows = get_data("SELECT id, word, definition FROM terms WHERE embedding IS NULL")
    
    # Pandas DataFrame으로 변환 (기존 로직과의 호환성을 위해)
    df = pd.DataFrame(rows)
    total_count = len(df)
    print(f"📦 임베딩 대상 데이터: {total_count}개")
    
    if total_count == 0:
        print("🎉 모든 데이터에 임베딩이 이미 존재합니다.")
        return

    # 2) 순회하며 임베딩 생성 및 업데이트
    print("🚀 벡터 생성 및 저장을 시작합니다...")
    
    for index, row in tqdm(df.iterrows(), total=total_count, desc="Processing"):
        try:
            # 검색 정확도를 높이기 위해 '용어'와 '정의'를 결합하여 임베딩
            combined_text = f"{row['word']}: {row['definition']}"
            
            # API 호출
            vector = get_embedding(combined_text)
            
            # [변경] execute_query를 사용하여 건별 업데이트
            # handle_sql.execute_query는 실행 후 자동 commit 됩니다.
            update_sql = "UPDATE terms SET embedding = %s WHERE id = %s"
            
            # JSON 직렬화 후 저장
            execute_query(update_sql, (json.dumps(vector), row['id']))
            
        except Exception as e:
            print(f"\n❌ ID {row['id']} ({row['word']}) 처리 중 오류: {e}")
            continue

    print("\n🎉 임베딩 생성 및 저장이 완료되었습니다!")

if __name__ == "__main__":
    add_embedding_column()
    generate_and_save_embeddings()