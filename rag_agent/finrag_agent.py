import os
from pathlib import Path
from dotenv import load_dotenv

# LangChain 관련 라이브러리
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# [NEW] 웹 검색 모듈 임포트
from rag_agent.web_search_rag import WebSearchRAG

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
# L2 Distance 기준: 0.6보다 크면 관련 없는 문서로 판단
SIMILARITY_THRESHOLD = 0.6

# [설정] 웹 검색을 강제할 키워드 목록
WEB_SEARCH_KEYWORDS = ["현재", "최신", "오늘", "주가", "시세", "뉴스", "전망", "날씨", "검색해줘", "얼마야"]

# 전역 변수
vectorstore = None
llm = ChatOpenAI(model="gpt-5-mini")
web_rag = WebSearchRAG() # 웹 검색 인스턴스 생성

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

def format_web_result(web_result, original_query, translated_query):
    """웹 검색 결과를 기존 RAG 답변 포맷으로 변환"""
    citations = [f"- **{src['title']}**: {src['url']}" for src in web_result.get('sources', [])]
    citation_text = "\n".join(citations) if citations else "- 출처 정보 없음"

    return f"""
### 🌏 질문
- **Original**: {original_query if original_query else translated_query}
- **Translated**: {translated_query}

### 🌐 FinBot의 웹 검색 답변
{web_result['answer']}

---
### 📚 참고 웹사이트
{citation_text}
"""

def get_rag_answer(korean_query, original_query=None):
    if vectorstore is None: load_knowledge_base()

    # ---------------------------------------------------------
    # [Logic 1] 실시간성/검색 의도 키워드 체크 -> 즉시 웹 검색
    # ---------------------------------------------------------
    if any(keyword in korean_query for keyword in WEB_SEARCH_KEYWORDS):
        print(f"🚀 [FinRAG] 실시간 키워드 감지 -> 웹 검색 전환: '{korean_query}'")
        web_result = web_rag.web_search(korean_query)
        return format_web_result(web_result, original_query, korean_query)

    # ---------------------------------------------------------
    # [Logic 2] ChromaDB 검색 수행
    # ---------------------------------------------------------
    relevant_docs = []
    if vectorstore:
        try:
            results = vectorstore.similarity_search_with_score(korean_query, k=5)
            print(f"🔍 [Search] '{korean_query}' DB 검색 수행")
            
            for doc, score in results:
                # L2 Distance는 0에 가까울수록 유사함 (Threshold 이하만 채택)
                if score <= SIMILARITY_THRESHOLD:
                    relevant_docs.append((doc, score))
                    print(f"   ✅ 채택: {doc.metadata.get('word')} (거리: {score:.4f})")
                else:
                    print(f"   ❌ 제외: {doc.metadata.get('word')} (거리: {score:.4f} > {SIMILARITY_THRESHOLD})")
            
            # 상위 3개만 사용
            relevant_docs = relevant_docs[:3]
        except Exception as e:
            print(f"⚠️ DB 검색 중 오류: {e}")
            relevant_docs = []

    # ---------------------------------------------------------
    # [Logic 3] Fallback: DB에 정보가 없을 경우 -> 웹 검색 자동 전환
    # ---------------------------------------------------------
    if not relevant_docs:
        print(f"⚠️ [FinRAG] 내부 DB에 관련 정보 없음 (유효 문서 0개) -> 웹 검색 자동 전환")
        web_result = web_rag.web_search(korean_query)
        return format_web_result(web_result, original_query, korean_query)

    # ---------------------------------------------------------
    # [Logic 4] DB 기반 답변 생성 (기존 RAG 로직)
    # ---------------------------------------------------------
    context_text = ""
    citations = []
    
    for doc, score in relevant_docs:
        word = doc.metadata.get("word", "Term")
        raw_content = doc.page_content
        definition = raw_content.split(":", 1)[1].strip() if ":" in raw_content else raw_content
        
        context_text += f"- **{word}**: {definition}\n"
        citations.append(f"- **{word}**: {definition[:60]}... (거리: {score:.4f})")

    # 프롬프트 로딩 및 체인 생성
    system_template = load_prompt("finrag_01_system.md")
    rag_prompt = PromptTemplate.from_template(system_template)
    rag_chain = rag_prompt | llm | StrOutputParser()

    try:
        ai_answer = rag_chain.invoke({
            "context": context_text,
            "question": korean_query
        })
    except Exception as e:
        ai_answer = f"죄송합니다. 답변 생성 중 오류가 발생했습니다. ({e})"

    # 최종 출력 포맷팅
    final_output = f"""
### 🌏 질문
- **Original**: {original_query if original_query else korean_query}
- **Translated**: {korean_query}

### 💡 FinBot의 답변
{ai_answer}

---
### 📚 내부 참고 문헌
{chr(10).join(citations)}
    """
    
    return final_output

if __name__ == "__main__":
    load_knowledge_base()
    # Test 1: DB에 있는 내용
    print(get_rag_answer("금리가 뭐야?"))
    print("-" * 50)
    # Test 2: 실시간 정보 (키워드 트리거)
    print(get_rag_answer("현재 삼성전자 주가 알려줘"))
    print("-" * 50)
    # Test 3: DB에 없는 내용 (Fallback 트리거) -> 예를 들어 엉뚱한 질문
    print(get_rag_answer("아이유 최신 앨범 뭐야?"))