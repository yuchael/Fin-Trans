import os
import json
import time
import pandas as pd
from sqlalchemy import create_engine, text
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm  # 진행률 표시용

print("🚀 [Embedding] 데이터 벡터화 및 DB 저장 시작...")

# 1. 환경설정
load_dotenv()

# OpenAI 클라이언트 설정
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# DB 연결 설정
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "fin_dictionary")

def get_db_engine():
    db_url = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    return create_engine(db_url)

# 2. 임베딩 컬럼 추가 (없을 경우)
def add_embedding_column():
    engine = get_db_engine()
    with engine.connect() as conn:
        try:
            # MySQL 5.7+ 에서는 JSON 타입을 지원합니다.
            # 벡터 데이터는 실수(float)의 리스트이므로 JSON으로 저장하는 것이 가장 간편합니다.
            conn.execute(text("ALTER TABLE terms ADD COLUMN embedding JSON"))
            print("✅ 'embedding' 컬럼이 생성되었습니다.")
        except Exception as e:
            # 이미 컬럼이 있으면 오류가 발생할 수 있으니 패스 (혹은 확인 로직 추가)
            if "Duplicate column name" in str(e):
                print("ℹ️ 'embedding' 컬럼이 이미 존재합니다.")
            else:
                print(f"⚠️ 컬럼 추가 중 경고: {e}")

# 3. 임베딩 생성 함수 (OpenAI API)
def get_embedding(text, model="text-embedding-3-small"):
    text = text.replace("\n", " ")  # 줄바꿈 제거
    return client.embeddings.create(input=[text], model=model).data[0].embedding

# 4. 메인 로직
def generate_and_save_embeddings():
    engine = get_db_engine()
    
    # 1) 아직 임베딩이 없는 데이터만 조회 (비용 절약)
    query = "SELECT id, word, definition FROM terms WHERE embedding IS NULL"
    df = pd.read_sql(query, engine)
    
    total_count = len(df)
    print(f"📦 임베딩 대상 데이터: {total_count}개")
    
    if total_count == 0:
        print("🎉 모든 데이터에 임베딩이 이미 존재합니다.")
        return

    # 2) 순회하며 임베딩 생성 및 업데이트
    # DB 연결을 계속 열고 닫는 것보다, 배치 업데이트가 좋지만
    # 여기서는 진행 상황 확인을 위해 건별/소량 배치로 진행합니다.
    
    with engine.connect() as conn:
        for index, row in tqdm(df.iterrows(), total=total_count, desc="Processing"):
            try:
                # 검색 정확도를 높이기 위해 '용어'와 '정의'를 결합하여 임베딩
                combined_text = f"{row['word']}: {row['definition']}"
                
                # API 호출
                vector = get_embedding(combined_text)
                
                # DB 업데이트 (JSON 형태로 변환하여 저장)
                update_sql = text("UPDATE terms SET embedding = :emb WHERE id = :id")
                conn.execute(update_sql, {"emb": json.dumps(vector), "id": row['id']})
                
                # Rate Limit 방지를 위해 아주 살짝 대기 (필요 시)
                # time.sleep(0.05) 
                
            except Exception as e:
                print(f"\n❌ ID {row['id']} ({row['word']}) 처리 중 오류: {e}")
                continue
                
            # 트랜잭션 커밋 (데이터 안정성을 위해 10건마다 혹은 매번 커밋)
            conn.commit()

    print("\n🎉 임베딩 생성 및 저장이 완료되었습니다!")

if __name__ == "__main__":
    add_embedding_column()
    generate_and_save_embeddings()