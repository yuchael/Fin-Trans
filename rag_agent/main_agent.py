import os
import json
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# ---------------------------------------------------------
# [Import] 전문가 에이전트 모듈
# ---------------------------------------------------------
from rag_agent.sql_agent import get_sql_answer
from rag_agent.finrag_agent import get_rag_answer
from rag_agent.transfer_agent import get_transfer_answer
from rag_agent.web_search_rag import WebSearchRAG

# 환경 변수 로드
load_dotenv()

# LLM 설정
llm = ChatOpenAI(model="gpt-5-mini")

# [전역 설정]
# 1. 대화 요약 저장소 (메모리 대신 사용)
GLOBAL_CHAT_CONTEXT = {"summary": ""}

# [NEW] 전역 컨텍스트 초기화 함수 (app.py에서 로그아웃 시 호출)
def reset_global_context():
    """전역 대화 요약 초기화"""
    global GLOBAL_CHAT_CONTEXT
    GLOBAL_CHAT_CONTEXT["summary"] = ""
    print("🧹 [Memory] 전역 대화 요약이 초기화되었습니다.")

# 2. 웹 검색 에이전트 인스턴스 (재사용을 위해 전역 생성)
web_rag = WebSearchRAG()

# ---------------------------------------------------------
# [설정] 프롬프트 경로 설정 및 로딩 함수
# ---------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
PROMPT_DIR = CURRENT_DIR / "prompt" / "main"

def read_prompt(filename: str) -> str:
    """MD 파일을 읽어서 문자열로 반환하는 함수"""
    file_path = PROMPT_DIR / filename
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"❌ [Error] 프롬프트 파일을 찾을 수 없습니다: {file_path}")
        return ""

# ---------------------------------------------------------
# [Step 1] 언어 감지 및 한국어 번역 체인
# ---------------------------------------------------------
translation_template = read_prompt("main_01_translation.md")
translation_prompt = PromptTemplate.from_template(translation_template)
translation_chain = translation_prompt | llm | StrOutputParser()

# ---------------------------------------------------------
# [Step 2] 문맥 보정(Refinement) 체인
# ---------------------------------------------------------
refinement_template = read_prompt("main_02_refinement.md")
refinement_prompt = PromptTemplate.from_template(refinement_template)
refinement_chain = refinement_prompt | llm | StrOutputParser()

# ---------------------------------------------------------
# [Step 3] 의도 분류 체인 (Router)
# ---------------------------------------------------------
router_template = read_prompt("main_03_router.md")
router_prompt = PromptTemplate.from_template(router_template)
router_chain = router_prompt | llm | StrOutputParser()

# ---------------------------------------------------------
# [Step 4-System] 일상 대화 (System Prompt) 처리 체인
# ---------------------------------------------------------
system_prompt_template = read_prompt("main_04_system.md")
system_prompt_chain = PromptTemplate.from_template(system_prompt_template) | llm | StrOutputParser()

# ---------------------------------------------------------
# [Step 5] 최종 답변 역번역 체인
# ---------------------------------------------------------
re_translation_template = read_prompt("main_05_re_translation.md")
re_translation_prompt = PromptTemplate.from_template(re_translation_template)
re_translation_chain = re_translation_prompt | llm | StrOutputParser()

# ---------------------------------------------------------
# [NEW] 대화 요약 체인 (메모리 대체용)
# ---------------------------------------------------------
summarizer_template = read_prompt("main_06_summarizer.md")
summarizer_prompt = PromptTemplate.from_template(summarizer_template)
summarizer_chain = summarizer_prompt | llm | StrOutputParser()

def update_summary(current_summary, user_input, ai_output):
    """LLM을 이용해 대화 요약을 업데이트하는 함수"""
    try:
        new_summary = summarizer_chain.invoke({
            "current_summary": current_summary,
            "user_input": user_input,
            "ai_output": ai_output
        }).strip()
        return new_summary
    except Exception as e:
        print(f"⚠️ 요약 업데이트 실패: {e}")
        return current_summary

# ---------------------------------------------------------
# 메인 에이전트 실행 함수 (Orchestrator)
# ---------------------------------------------------------
def run_fintech_agent(question, username="test_user", transfer_context=None, allowed_views=None):
    """
    [Params]
    - question: 사용자 질문
    - username: 사용자 ID (SQL, 송금 등에서 사용)
    - transfer_context: 송금 진행 중인 상태 데이터 (있으면 즉시 송금 로직 수행)
    - allowed_views: SQL 에이전트가 조회 가능한 뷰 목록
    """
    print(f"\n[User Input]: {question}")

    # --- Step 1: 언어 감지 및 한국어 번역 ---
    try:
        trans_result_str = translation_chain.invoke({"question": question}).strip()
        trans_result_str = trans_result_str.replace("```json", "").replace("```", "")
        trans_result = json.loads(trans_result_str)
        
        source_lang = trans_result.get("source_language", "Korean")
        korean_query = trans_result.get("korean_query", question)
        print(f"🌐 [Step 1] 감지 언어: {source_lang} -> 변환: {korean_query}")
        
    except Exception as e:
        print(f"⚠️ 번역 오류: {e}")
        source_lang = "Korean"
        korean_query = question

    # ---------------------------------------------------------
    # [Priority Check] 송금 컨텍스트가 있으면 바로 송금 에이전트로 이동
    # ---------------------------------------------------------
    if transfer_context:
        print("💸 [System] 송금 진행 중... (Context 유지)")
        # [수정] 번역된 쿼리(korean_query)를 넘겨서, 외국어 입력 시에도 송금 에이전트가 이해하도록 함
        return get_transfer_answer(
            korean_query, 
            username,
            context=transfer_context
        )

    # --- Step 2: 질문 구체화 (Refinement) - 무조건 실행 ---
    current_history = GLOBAL_CHAT_CONTEXT["summary"]
    
    # history가 비어있을 경우 명시적인 텍스트 전달
    history_context = current_history if current_history else "이전 대화 기록 없음(No previous conversation history)."

    print(f"🧠 [Memory Summary]: {history_context}")

    refined_query = refinement_chain.invoke({
        "history": history_context,
        "question": korean_query
    }).strip()
    
    if refined_query != korean_query:
        print(f"✨ [Step 2] 질문 보정: '{korean_query}' -> '{refined_query}'")
    else:
        print(f"✨ [Step 2] 질문 보정 없음 (변화 없음)")

    # --- Step 3: 의도 파악 (Router) ---
    category = router_chain.invoke({"question": refined_query}).strip()
    # 특수문자 제거 정제
    category = category.replace("'", "").replace('"', "").replace(".", "")
    print(f"🕵️ [Step 3] 의도 분류: [{category}]")
    
    korean_answer = ""
    
    # --- Step 4: 전문가 호출 (Agent Execution) ---
    if category == "DATABASE":
        print("\n=== 🏦 SQL Agent 호출 ===")
        korean_answer = get_sql_answer(refined_query, username, allowed_views)
        print("=== 🏦 SQL Agent 종료 ===\n")
        
    elif category == "KNOWLEDGE":
        print("\n=== 🎓 FinRAG Agent (Hybrid) 호출 ===")
        korean_answer = get_rag_answer(refined_query, original_query=question)
        print("=== 🎓 FinRAG Agent 종료 ===\n")
        
    elif category == "TRANSFER":
        print("\n=== 💸 Transfer Agent 호출 ===")
        transfer_result = get_transfer_answer(refined_query, username, context=None)
        if isinstance(transfer_result, dict):
            return transfer_result
        korean_answer = transfer_result
        print("=== 💸 Transfer Agent 종료 ===\n")

    elif category == "GENERAL":
        print("\n=== 💬 System Prompt 호출 ===")
        korean_answer = system_prompt_chain.invoke({"question": korean_query})
        print("=== 💬 System Prompt 종료 ===\n")
        
    else:
        korean_answer = "죄송해요, 질문의 의도를 정확히 파악하지 못했습니다."
        print(f"❌ [Exception] 처리 불가 카테고리: {category}")

    # --- [NEW] 대화 내용 요약 업데이트 (송금 진행 중이 아닐 때만) ---
    if isinstance(korean_answer, str):
        print("📝 [Memory] 대화 요약 업데이트 중...")
        updated_summary = update_summary(current_history, refined_query, korean_answer)
        GLOBAL_CHAT_CONTEXT["summary"] = updated_summary
        print(f"✅ [Memory Updated]: {updated_summary[:50]}...")

    # --- Step 5: 최종 답변 역번역 ---
    if isinstance(korean_answer, str) and "Korean" not in source_lang and "한국어" not in source_lang:
        print(f"🔄 [Step 5] 답변 역번역 중...")
        foreign_answer = re_translation_chain.invoke({
            "target_language": source_lang, 
            "korean_answer": korean_answer
        })
        final_answer = f"""
{foreign_answer}

=========================================
📢 [한국어 번역본 / Demo Translation]
{korean_answer}
=========================================
"""
    else:
        final_answer = korean_answer

    return final_answer