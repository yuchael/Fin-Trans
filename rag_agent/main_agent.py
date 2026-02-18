import os
import json
from pathlib import Path
from typing import TypedDict, Literal
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END
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
# [LangGraph] 상태 스키마
# ---------------------------------------------------------
class MainAgentState(TypedDict, total=False):
    question: str
    korean_query: str
    source_lang: str
    refined_query: str
    category: str
    korean_answer: str
    final_answer: str
    transfer_result: dict
    username: str
    transfer_context: dict
    allowed_views: list
    # 내부용
    _history: str
    _skip_re_translate: bool

# ---------------------------------------------------------
# [LangGraph] 프롬프트/체인 빌더 (노드에서 사용)
# ---------------------------------------------------------
def _translation_chain():
    t = read_prompt("main_01_translation.md")
    return PromptTemplate.from_template(t) | llm | StrOutputParser()

def _refinement_chain():
    t = read_prompt("main_02_refinement.md")
    return PromptTemplate.from_template(t) | llm | StrOutputParser()

def _router_chain():
    t = read_prompt("main_03_router.md")
    return PromptTemplate.from_template(t) | llm | StrOutputParser()

def _system_prompt_chain():
    t = read_prompt("main_04_system.md")
    return PromptTemplate.from_template(t) | llm | StrOutputParser()

def _re_translation_chain():
    t = read_prompt("main_05_re_translation.md")
    return PromptTemplate.from_template(t) | llm | StrOutputParser()

def _summarizer_chain():
    t = read_prompt("main_06_summarizer.md")
    return PromptTemplate.from_template(t) | llm | StrOutputParser()

# ---------------------------------------------------------
# 역번역 헬퍼 함수 (모든 답변에 적용)
# ---------------------------------------------------------
def translate_answer(korean_text: str, target_language: str) -> str:
    """
    한국어 답변을 사용자 입력 언어로 번역
    - 한국어면 그대로 반환
    - 다른 언어면 역번역 수행
    """
    if not korean_text:
        return korean_text
    
    # 한국어면 번역 불필요
    if "Korean" in target_language or "한국어" in target_language:
        return korean_text
    
    try:
        print(f"🔄 [Translation] 답변을 {target_language}로 번역 중...")
        chain = _re_translation_chain()
        translated = chain.invoke({
            "target_language": target_language,
            "korean_answer": korean_text
        }).strip()
        return translated
    except Exception as e:
        print(f"⚠️ 역번역 실패: {e}, 원본 반환")
        return korean_text

# ---------------------------------------------------------
# [LangGraph] 노드 함수
# ---------------------------------------------------------
def node_translate(state: MainAgentState) -> dict:
    question = state["question"]
    try:
        chain = _translation_chain()
        trans_result_str = chain.invoke({"question": question}).strip()
        trans_result_str = trans_result_str.replace("```json", "").replace("```", "")
        trans_result = json.loads(trans_result_str)
        source_lang = trans_result.get("source_language", "Korean")
        korean_query = trans_result.get("korean_query", question)
        print(f"🌐 [Step 1] 감지 언어: {source_lang} -> 변환: {korean_query}")
    except Exception as e:
        print(f"⚠️ 번역 오류: {e}")
        source_lang = "Korean"
        korean_query = question
    return {"korean_query": korean_query, "source_lang": source_lang}

def node_refine(state: MainAgentState) -> dict:
    history_context = state.get("_history") or "이전 대화 기록 없음(No previous conversation history)."
    korean_query = state["korean_query"]
    print(f"🧠 [Memory Summary]: {history_context}")
    chain = _refinement_chain()
    refined_query = chain.invoke({"history": history_context, "question": korean_query}).strip()
    if refined_query != korean_query:
        print(f"✨ [Step 2] 질문 보정: '{korean_query}' -> '{refined_query}'")
    else:
        print(f"✨ [Step 2] 질문 보정 없음 (변화 없음)")
    return {"refined_query": refined_query}

def node_route(state: MainAgentState) -> dict:
    chain = _router_chain()
    category = chain.invoke({"question": state["refined_query"]}).strip()
    category = category.replace("'", "").replace('"', "").replace(".", "")
    print(f"🕵️ [Step 3] 의도 분류: [{category}]")
    return {"category": category}

def node_sql(state: MainAgentState) -> dict:
    print("\n=== 🏦 SQL Agent 호출 ===")
    answer = get_sql_answer(
        state["refined_query"],
        state["username"],
        state.get("allowed_views") or []
    )
    print("=== 🏦 SQL Agent 종료 ===\n")
    return {"korean_answer": answer}

def node_finrag(state: MainAgentState) -> dict:
    print("\n=== 🎓 FinRAG Agent (Hybrid) 호출 ===")
    answer = get_rag_answer(state["refined_query"], original_query=state["question"])
    print("=== 🎓 FinRAG Agent 종료 ===\n")
    return {"korean_answer": answer}

def node_transfer(state: MainAgentState) -> dict:
    print("\n=== 💸 Transfer Agent 호출 ===")
    # 최초 송금 요청 시 언어를 컨텍스트에 저장하기 위해 빈 컨텍스트 전달
    result = get_transfer_answer(state["refined_query"], state["username"], context={})
    if isinstance(result, dict):
        # 최초 요청이면 언어 정보를 컨텍스트에 저장
        if result.get("context") and not result["context"].get("source_language"):
            source_lang = state.get("source_lang", "Korean")
            result["context"]["source_language"] = source_lang
        return {"transfer_result": result, "korean_answer": None}
    print("=== 💸 Transfer Agent 종료 ===\n")
    return {"korean_answer": result, "transfer_result": None}

def node_system(state: MainAgentState) -> dict:
    print("\n=== 💬 System Prompt 호출 ===")
    chain = _system_prompt_chain()
    answer = chain.invoke({"question": state["korean_query"]})
    print("=== 💬 System Prompt 종료 ===\n")
    return {"korean_answer": answer}

def node_fallback(state: MainAgentState) -> dict:
    korean_answer = "죄송해요, 질문의 의도를 정확히 파악하지 못했습니다."
    print(f"❌ [Exception] 처리 불가 카테고리: {state.get('category', '')}")
    return {"korean_answer": korean_answer}

def node_summarize(state: MainAgentState) -> dict:
    current_history = state.get("_history") or ""
    refined_query = state.get("refined_query", "")
    korean_answer = state.get("korean_answer") or ""
    if not isinstance(korean_answer, str):
        return {}
    print("📝 [Memory] 대화 요약 업데이트 중...")
    try:
        chain = _summarizer_chain()
        new_summary = chain.invoke({
            "current_summary": current_history,
            "user_input": refined_query,
            "ai_output": korean_answer
        }).strip()
        GLOBAL_CHAT_CONTEXT["summary"] = new_summary
        print(f"✅ [Memory Updated]: {new_summary[:50]}...")
    except Exception as e:
        print(f"⚠️ 요약 업데이트 실패: {e}")
    return {}

def node_re_translate(state: MainAgentState) -> dict:
    """모든 답변을 사용자 입력 언어로 역번역"""
    source_lang = state.get("source_lang", "Korean")
    korean_answer = state.get("korean_answer", "")
    final_answer = translate_answer(korean_answer, source_lang)
    return {"final_answer": final_answer}

# ---------------------------------------------------------
# 라우터: 카테고리별 다음 노드
# ---------------------------------------------------------
def route_by_category(state: MainAgentState) -> Literal["sql", "finrag", "transfer", "system", "fallback"]:
    cat = (state.get("category") or "").strip()
    if cat == "DATABASE":
        return "sql"
    if cat == "KNOWLEDGE":
        return "finrag"
    if cat == "TRANSFER":
        return "transfer"
    if cat == "GENERAL":
        return "system"
    return "fallback"

# transfer 노드 결과가 dict면 END로 (송금 플로우는 별도 반환)
def after_transfer(state: MainAgentState) -> Literal["summarize", "end_transfer"]:
    if state.get("transfer_result") is not None:
        return "end_transfer"
    return "summarize"

# ---------------------------------------------------------
# [LangGraph] 그래프 빌드 및 컴파일
# ---------------------------------------------------------
def _build_main_graph():
    builder = StateGraph(MainAgentState)

    builder.add_node("translate", node_translate)
    builder.add_node("refine", node_refine)
    builder.add_node("route", node_route)
    builder.add_node("sql", node_sql)
    builder.add_node("finrag", node_finrag)
    builder.add_node("transfer", node_transfer)
    builder.add_node("system", node_system)
    builder.add_node("fallback", node_fallback)
    builder.add_node("summarize", node_summarize)
    builder.add_node("re_translate", node_re_translate)

    builder.add_edge(START, "translate")
    builder.add_edge("translate", "refine")
    builder.add_edge("refine", "route")
    builder.add_conditional_edges("route", route_by_category, {
        "sql": "sql",
        "finrag": "finrag",
        "transfer": "transfer",
        "system": "system",
        "fallback": "fallback",
    })
    builder.add_conditional_edges("transfer", after_transfer, {"end_transfer": END, "summarize": "summarize"})
    builder.add_edge("sql", "summarize")
    builder.add_edge("finrag", "summarize")
    builder.add_edge("system", "summarize")
    builder.add_edge("fallback", "summarize")
    builder.add_edge("summarize", "re_translate")
    builder.add_edge("re_translate", END)

    return builder.compile()

# 전역 컴파일된 그래프 (캐시)
_compiled_graph = None

def get_main_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_main_graph()
    return _compiled_graph

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

    # [Priority] 송금 컨텍스트가 있으면 LangGraph 거치지 않고 바로 송금 에이전트
    if transfer_context:
        print("💸 [System] 송금 진행 중... (Context 유지)")
        
        # 최초 질문의 언어를 컨텍스트에서 가져오기 (없으면 현재 입력으로 감지)
        source_lang = transfer_context.get("source_language", "Korean")
        
        # 버튼 신호나 숫자 입력은 번역하지 않음 (저장된 언어 사용)
        if question.strip().upper() in ("__YES__", "__NO__"):
            korean_query = question
            # 저장된 언어가 없으면 기본값 사용 (이미 위에서 설정됨)
        elif question.strip().isdigit() or (len(question.strip()) <= 10 and not any(c.isalpha() for c in question)):
            # 숫자나 짧은 비문자 입력(PIN 등)은 번역하지 않고, 저장된 언어 사용
            korean_query = question
        else:
            # 텍스트 입력이면 언어 감지 시도
            try:
                chain = _translation_chain()
                trans_result_str = chain.invoke({"question": question}).strip()
                trans_result_str = trans_result_str.replace("```json", "").replace("```", "")
                trans_result = json.loads(trans_result_str)
                detected_lang = trans_result.get("source_language", "Korean")
                korean_query = trans_result.get("korean_query", question)
                
                # 컨텍스트에 언어가 없으면 새로 감지한 언어 저장
                if source_lang == "Korean" and detected_lang != "Korean":
                    source_lang = detected_lang
                    transfer_context["source_language"] = source_lang
            except Exception:
                korean_query = question
        
        # 송금 에이전트 호출
        transfer_result = get_transfer_answer(korean_query, username, context=transfer_context)
        
        # dict 반환 시 message 필드 역번역 (저장된 언어 사용)
        if isinstance(transfer_result, dict) and "message" in transfer_result:
            korean_msg = transfer_result["message"]
            translated_msg = translate_answer(korean_msg, source_lang)
            transfer_result["message"] = translated_msg
            # 컨텍스트에 언어 정보 유지 (진행 중 상태일 때)
            if "context" in transfer_result:
                transfer_result["context"]["source_language"] = source_lang
        
        return transfer_result

    initial_state: MainAgentState = {
        "question": question,
        "username": username,
        "allowed_views": allowed_views or [],
        "_history": GLOBAL_CHAT_CONTEXT["summary"],
    }

    graph = get_main_graph()
    result = graph.invoke(initial_state)

    # 송금 결과가 dict면 message 필드 역번역 후 반환
    if result.get("transfer_result") is not None:
        transfer_result = result["transfer_result"]
        source_lang = result.get("source_lang", "Korean")
        if isinstance(transfer_result, dict) and "message" in transfer_result:
            korean_msg = transfer_result["message"]
            translated_msg = translate_answer(korean_msg, source_lang)
            transfer_result["message"] = translated_msg
        return transfer_result

    return result.get("final_answer") or result.get("korean_answer") or ""
