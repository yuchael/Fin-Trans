import os
import json
import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from openai import OpenAI
from dotenv import load_dotenv

# 1. 환경 설정
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "fintech_agent")

# 전역 변수 선언 (데이터를 한 번만 로딩하기 위함)
df = None
embedding_matrix = None

def load_knowledge_base():
    """DB에서 금융 지식을 로드하고 벡터 행렬을 생성합니다."""
    global df, embedding_matrix
    if df is not None:
        return # 이미 로딩되었다면 스킵

    print("⏳ [RAG] 금융 지식 베이스를 로딩 중입니다...")
    db_url = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    engine = create_engine(db_url)

    df = pd.read_sql("SELECT word, definition, embedding FROM terms", engine)
    df['embedding'] = df['embedding'].apply(json.loads)
    embedding_matrix = np.vstack(df['embedding'].values)
    print(f"✅ 로딩 완료! (총 {len(df)}개 용어)")

# 유틸리티 함수
def get_embedding(text):
    return client.embeddings.create(input=[text], model="text-embedding-3-small").data[0].embedding

def search_docs(query_text, top_k=3):
    query_vec = get_embedding(query_text)
    similarities = np.dot(embedding_matrix, query_vec) / (
        np.linalg.norm(embedding_matrix, axis=1) * np.linalg.norm(query_vec)
    )
    df['similarity'] = similarities
    return df.sort_values('similarity', ascending=False).head(top_k)

def translate_query_to_korean(user_query):
    """외국어 질문을 한국어 검색 키워드로 변환합니다."""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": """
             You are a sophisticated translation assistant for a Korean Financial Terminology Search Engine.
             Your goal is to convert the user's query into the most appropriate Korean financial keyword.
             Output ONLY the Korean keyword(s).
             """},
            {"role": "user", "content": user_query}
        ],
        temperature=0
    )
    return response.choices[0].message.content.strip()

# 🔥 외부(main_agent.py)에서 호출할 공식 함수
def get_rag_answer(user_query):
    # 호출 시점에 데이터가 로드 안 되어 있다면 로드
    if df is None:
        load_knowledge_base()

    # [수정 1] 번역 단계 삭제 (이미 main_agent에서 한국어로 줌)
    # korean_search_term = translate_query_to_korean(user_query) <- 삭제
    korean_search_term = user_query # 받은 그대로 검색어로 사용

    # 2. 검색 단계
    relevant_docs = search_docs(korean_search_term)
    
    # 유사도 체크 (관련성 낮은 경우 방어)
    if relevant_docs.iloc[0]['similarity'] < 0.30:
        return "죄송합니다. 해당 질문과 관련된 금융 지식을 찾지 못했습니다."

    # 3. 컨텍스트 구성
    context_text = ""
    for idx, row in relevant_docs.iterrows():
        context_text += f"Term: {row['word']}\nDefinition: {row['definition']}\n\n"

    # [수정 2] 시스템 프롬프트 변경 (한국어 답변 강제)
    system_prompt = f"""
    You are a helpful Financial Expert AI. 
    Explain the financial concept based on the [Context].
    
    [Rules]
    1. Answer ONLY in Korean. (무조건 한국어로 답변하세요)
    2. Explain clearly and easily.
    
    [Context]
    {context_text}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ],
        temperature=0
    )

    return response.choices[0].message.content.strip()

# 단독 테스트용
if __name__ == "__main__":
    # 단독 실행 시에만 로딩 및 루프 가동
    load_knowledge_base()
    while True:
        inp = input("\nQ (exit to quit): ")
        if inp.lower() in ['exit', 'quit']: break
        print(f"\nA: {get_rag_answer(inp)}")