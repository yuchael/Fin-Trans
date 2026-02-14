import os
from pathlib import Path
from dotenv import load_dotenv

# LangChain 관련 라이브러리
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 1. 환경 설정
load_dotenv()

# 경로 설정
CURRENT_FILE_PATH = Path(__file__).resolve() 
PROJECT_ROOT = CURRENT_FILE_PATH.parent.parent 
PROMPT_DIR = CURRENT_FILE_PATH.parent / "prompt" / "finrag"

# ChromaDB 데이터 경로
CHROMA_DB_PATH = PROJECT_ROOT / "data" / "financial_terms"
COLLECTION_NAME = "financial_terms"

# [설정] 검색 품질을 위한 임계값 (Threshold)
# 거리(Distance) 기준이므로, 이 값보다 '작아야' 유사한 문서입니다.
# L2 Distance 기준: 0.5 ~ 0.8 사이 권장 (데이터 분포에 따라 조절 필요)
SIMILARITY_THRESHOLD = 0.6

# 전역 변수
vectorstore = None
llm = ChatOpenAI(model="gpt-5-mini")

def load_prompt(filename: str) -> str:
    """MD 파일을 읽어서 문자열로 반환하는 함수"""
    file_path = PROMPT_DIR / filename
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"❌ [Error] 프롬프트 파일을 찾을 수 없습니다: {file_path}")
        return "{context}\n{question}"

def load_knowledge_base():
    """ChromaDB 연결 설정"""
    global vectorstore
    if vectorstore is not None: return

    print("⏳ [RAG] ChromaDB 연결 중...")
    try:
        embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
        
        # [변경] 거리 측정 방식 변경 (cosine -> l2)
        # 주의: DB를 새로 생성해야 완벽하게 적용됩니다.
        vectorstore = Chroma(
            persist_directory=str(CHROMA_DB_PATH),
            embedding_function=embeddings,
            collection_name=COLLECTION_NAME,
            collection_metadata={"hnsw:space": "l2"} 
        )
        print(f"✅ ChromaDB 연결 완료 (Metirc: L2, 경로: {CHROMA_DB_PATH})")
        
    except Exception as e:
        print(f"❌ ChromaDB 연결 오류: {e}")
        vectorstore = None

def get_rag_answer(korean_query, original_query=None):
    if vectorstore is None: load_knowledge_base()

    # 1. 문서 검색 (Score 포함)
    relevant_docs = []
    if vectorstore:
        # 넉넉하게 5개를 가져온 뒤 필터링
        results = vectorstore.similarity_search_with_score(korean_query, k=5)
        
        # [추가] Threshold 필터링 로직
        print(f"🔍 [Search] '{korean_query}' 검색 결과 (Threshold: {SIMILARITY_THRESHOLD})")
        for doc, score in results:
            # L2 Distance는 0에 가까울수록 유사함
            if score <= SIMILARITY_THRESHOLD:
                relevant_docs.append((doc, score))
                print(f"   ✅ 채택: {doc.metadata.get('word')} (거리: {score:.4f})")
            else:
                print(f"   ❌ 제외: {doc.metadata.get('word')} (거리: {score:.4f} > {SIMILARITY_THRESHOLD})")
        
        # 상위 3개만 사용
        relevant_docs = relevant_docs[:3]
    
    # 2. 컨텍스트 및 출처(Citation) 구성
    context_text = ""
    citations = []
    
    if relevant_docs:
        for doc, score in relevant_docs:
            # L2 거리일 때는 유사도(%) 표현이 애매하므로 거리값 자체를 표기하거나 생략
            # 여기서는 편의상 거리(Distance)를 그대로 표시합니다.
            
            word = doc.metadata.get("word", "Term")
            raw_content = doc.page_content
            
            definition = raw_content.split(":", 1)[1].strip() if ":" in raw_content else raw_content
            
            context_text += f"- **{word}**: {definition}\n"
            citations.append(f"- **{word}**: {definition[:60]}... (거리: {score:.4f})")
            
    else:
        print("⚠️ [Retrieved Docs]: 유효한 검색 결과 없음 (Threshold 미달)")
        context_text = "" 
        citations.append("- 관련된 내부 데이터가 없습니다 (검색 기준 미달).")

    # 3. 프롬프트 로딩 및 체인 생성
    system_template = load_prompt("finrag_01_system.md")
    rag_prompt = PromptTemplate.from_template(system_template)
    rag_chain = rag_prompt | llm | StrOutputParser()

    # 4. LLM 호출
    try:
        # 검색 결과가 없으면(context_text가 비었으면) 프롬프트에서 Fallback 처리가 되도록 유도
        ai_answer = rag_chain.invoke({
            "context": context_text if context_text else "검색된 문서가 없습니다.",
            "question": korean_query
        })
    except Exception as e:
        ai_answer = f"죄송합니다. 답변 생성 중 오류가 발생했습니다. ({e})"

    # 5. 최종 출력 포맷팅
    final_output = f"""
### 🌏 질문 (Question)
- **Original**: {original_query if original_query else korean_query}
- **Translated**: {korean_query}

### 💡 FinBot의 답변
{ai_answer}

---
### 📚 참고 문헌 (References)
{chr(10).join(citations)}
    """
    
    return final_output

if __name__ == "__main__":
    load_knowledge_base()
    # 테스트
    print(get_rag_answer("금리가 뭐야?"))