import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from utils.handle_sql import get_data  # DB 연결 모듈

# 1. 환경 설정
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 전역 변수
df = None
embedding_matrix = None

# 프롬프트 파일 경로 설정
CURRENT_FILE_PATH = Path(__file__).resolve() 
PROJECT_ROOT = CURRENT_FILE_PATH.parent.parent 
PROMPT_PATH = PROJECT_ROOT / "utils" / "system_prompt.md" 

def load_knowledge_base():
    """DB 데이터 로딩"""
    global df, embedding_matrix
    if df is not None: return

    print("⏳ [RAG] 금융 지식 베이스 로딩 중...")
    try:
        rows = get_data("SELECT word, definition, embedding FROM terms")
        df = pd.DataFrame(rows)
        
        if df.empty:
            print("⚠️ 데이터 없음.")
            return

        df['embedding'] = df['embedding'].apply(json.loads)
        embedding_matrix = np.vstack(df['embedding'].values)
        print(f"✅ 로딩 완료 ({len(df)}개)")
    except Exception as e:
        print(f"❌ 로딩 오류: {e}")
        df = None

def get_embedding(text):
    return client.embeddings.create(input=[text], model="text-embedding-3-small").data[0].embedding

def search_docs(query_text, top_k=3):
    if df is None: return pd.DataFrame()
    
    query_vec = get_embedding(query_text)
    similarities = np.dot(embedding_matrix, query_vec) / (
        np.linalg.norm(embedding_matrix, axis=1) * np.linalg.norm(query_vec)
    )
    df['similarity'] = similarities
    # 유사도 0.3 이상인 것만 필터링 (너무 엉뚱한 문서 제외)
    return df[df['similarity'] >= 0.3].sort_values('similarity', ascending=False).head(top_k)

def read_prompt_file():
    """MD 파일에서 시스템 프롬프트 읽기"""
    try:
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "You are a helpful assistant." # 파일 없을 시 기본값

# 🔥 핵심 함수: 인자에 original_query 추가
def get_rag_answer(korean_query, original_query=None):
    if df is None: load_knowledge_base()

    # 1. 문서 검색
    relevant_docs = search_docs(korean_query, top_k=3)
    
    # 2. 컨텍스트 및 출처(Citation) 구성
    context_text = ""
    citations = []
    
    if not relevant_docs.empty:
        for idx, row in relevant_docs.iterrows():
            context_text += f"Term: {row['word']}\nDefinition: {row['definition']}\n\n"
            citations.append(f"- **{row['word']}**: {row['definition'][:50]}... (유사도: {row['similarity']:.2f})")
    else:
        context_text = "관련된 DB 정보가 없습니다. 일반적인 지식을 활용하세요."
        citations.append("- 검색된 관련 문서가 없습니다.")

    # 3. 프롬프트 로딩 및 구성
    system_template = read_prompt_file()
    formatted_system_prompt = system_template.format(context=context_text)

    # 4. LLM 호출
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": formatted_system_prompt},
            {"role": "user", "content": f"질문에 대해 초등학생 선생님처럼 핵심만 짧게 답변해 주세요: {korean_query}"}
        ],
        temperature=0.3
    )
    
    ai_answer = response.choices[0].message.content.strip()

    # 5. 최종 출력 포맷팅 (요청하신 부분)
    final_output = f"""
### 🌏 질문 (Question)
- **Original**: {original_query if original_query else korean_query}
- **Translated**: {korean_query}

### 💡 선생님의 답변
{ai_answer}

---
### 📚 참고 문헌 (References)
{chr(10).join(citations)}
    """
    
    return final_output

if __name__ == "__main__":
    load_knowledge_base()
    print(get_rag_answer("집을 구하려면 어떻게 해야해?", "How can I find a house?"))