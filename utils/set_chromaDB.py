import os
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

# 제공해주신 handle_sql 모듈에서 get_data 함수 임포트
# (파일 위치에 따라 from handle_sql import get_data 로 변경 필요할 수 있음)
try:
    from utils.handle_sql import get_data
except ImportError:
    from handle_sql import get_data

# .env 로드
load_dotenv()

# ==========================================
# 1. 설정 (Configuration)
# ==========================================
# 저장 경로 수정: 상위 폴더(..)의 data/financial_terms
current_script_path = os.path.abspath(__file__)

# 2. 이 파일이 있는 디렉토리(utils 폴더)를 구합니다.
current_script_dir = os.path.dirname(current_script_path)

# 3. 그 디렉토리(utils)의 상위(..)로 가서 data/financial_terms를 지정합니다.
PERSIST_DIRECTORY = os.path.join(current_script_dir, "..", "data", "financial_terms")

# 4. 경로를 깔끔하게 정리합니다 (예: /utils/../data -> /data)
PERSIST_DIRECTORY = os.path.normpath(PERSIST_DIRECTORY)

print(f"📍 확정된 저장 경로: {PERSIST_DIRECTORY}") # 확인용 출력

COLLECTION_NAME = "financial_terms"
BATCH_SIZE = 100

# ==========================================
# 2. ChromaDB 초기화
# ==========================================
# OpenAI 임베딩 함수 설정
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=os.getenv("OPENAI_API_KEY"),
    model_name="text-embedding-3-large"
)

# PersistentClient 설정 (데이터가 파일로 저장됨)
client = chromadb.PersistentClient(path=PERSIST_DIRECTORY)

# 컬렉션 가져오기 또는 생성
collection = client.get_or_create_collection(
    name=COLLECTION_NAME,
    embedding_function=openai_ef
)

def sync_mysql_to_chroma():
    print(f"📂 저장 경로: {os.path.abspath(PERSIST_DIRECTORY)}")
    print("🔄 MySQL 데이터 조회 시작...")

    try:
        # ---------------------------------------------------------
        # Step 1: handle_sql 모듈을 통해 데이터 조회 (매우 간결해짐!)
        # ---------------------------------------------------------
        sql = "SELECT id, word, definition FROM terms WHERE definition IS NOT NULL"
        rows = get_data(sql)  # DB 연결/커서/해제 로직이 이 함수 안에 다 있음

        if not rows:
            print("⚠️ 저장할 데이터가 없습니다.")
            return

        print(f"📊 총 {len(rows)}개의 데이터를 가져왔습니다.")

        # ---------------------------------------------------------
        # Step 2: 데이터 가공
        # ---------------------------------------------------------
        ids_list = []
        documents_list = []
        metadatas_list = []

        for row in rows:
            # ChromaDB ID는 반드시 문자열(String)이어야 함
            doc_id = str(row['id'])
            
            # 요청하신 포맷: "word: definition"
            content = f"{row['word']}: {row['definition']}"
            
            # 메타데이터 구성
            metadata = {
                "original_id": row['id'],
                "word": row['word']
            }

            ids_list.append(doc_id)
            documents_list.append(content)
            metadatas_list.append(metadata)

        # ---------------------------------------------------------
        # Step 3: 배치 단위로 ChromaDB에 저장 (Upsert)
        # ---------------------------------------------------------
        print("💾 ChromaDB 저장(Upsert) 시작...")
        
        total_count = len(ids_list)
        
        for i in range(0, total_count, BATCH_SIZE):
            # 슬라이싱으로 배치 나누기
            batch_ids = ids_list[i : i + BATCH_SIZE]
            batch_docs = documents_list[i : i + BATCH_SIZE]
            batch_metas = metadatas_list[i : i + BATCH_SIZE]

            # Upsert (기존에 있으면 업데이트, 없으면 추가)
            collection.upsert(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_metas
            )
            
            # 진행 상황 출력
            current_progress = min(i + BATCH_SIZE, total_count)
            print(f"   - Progress: {current_progress} / {total_count} 완료")

        print("✅ 모든 데이터 동기화 완료!")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    sync_mysql_to_chroma()