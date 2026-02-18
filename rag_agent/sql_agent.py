import os
from pathlib import Path
from typing import TypedDict
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END

from utils.handle_sql import get_data

# 1. 환경 변수 로드
load_dotenv()

# 2. LLM 설정
llm = ChatOpenAI(model="gpt-5-mini")

# ---------------------------------------------------------
# [설정] 프롬프트 경로 설정 및 로딩 함수
# ---------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
PROMPT_DIR = CURRENT_DIR.parent / "rag_agent" / "prompt" / "sql"

def read_prompt(filename: str) -> str:
    file_path = PROMPT_DIR / filename
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"❌ [Error] 프롬프트 파일을 찾을 수 없습니다: {file_path}")
        return ""

# ---------------------------------------------------------
# DB 유틸리티 함수
# ---------------------------------------------------------
def get_schema_info(allowed_views: list):
    try:
        if not allowed_views:
            return "No accessible tables provided."
        schema_text = ""
        for view_name in allowed_views:
            schema_text += f"\n[Table/View: {view_name}]\n"
            columns = get_data(f"DESCRIBE {view_name}")
            if columns:
                for col in columns:
                    schema_text += f"- {col['Field']} ({col['Type']})\n"
            else:
                schema_text += "- (No columns found or permission denied)\n"
        return schema_text.strip()
    except Exception as e:
        return f"스키마 조회 실패: {e}"

def clean_sql_query(text: str) -> str:
    text = text.strip()
    if text.startswith("SQLQuery:"):
        text = text.replace("SQLQuery:", "").strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            if part.lower().strip().startswith("sql"):
                text = part.strip()[3:].strip()
                break
            elif len(part) > 10 and "select" in part.lower():
                text = part.strip()
                break
    return text.strip()

def run_db_query(query, username):
    try:
        if not query:
            return "생성된 쿼리가 없습니다."
        print(f"🔄 [DB Executing]: {query}")
        result = get_data(query)
        if not result:
            return "검색 결과가 없습니다."
        return str(result)
    except Exception as e:
        return f"SQL 실행 오류: {e}"

# ---------------------------------------------------------
# [LangGraph] SQL 에이전트 상태
# ---------------------------------------------------------
class SQLAgentState(TypedDict, total=False):
    question: str
    username: str
    allowed_views: list
    schema: str
    query: str
    result: str
    response: str

# ---------------------------------------------------------
# [LangGraph] 노드
# ---------------------------------------------------------
def node_schema(state: SQLAgentState) -> dict:
    schema = get_schema_info(state.get("allowed_views") or [])
    return {"schema": schema}

def node_sql_gen(state: SQLAgentState) -> dict:
    template = read_prompt("sql_01_generation.md")
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    raw = chain.invoke({
        "question": state["question"],
        "schema": state["schema"],
    })
    query = clean_sql_query(raw)
    return {"query": query}

def node_execute(state: SQLAgentState) -> dict:
    result = run_db_query(state["query"], state["username"])
    return {"result": result}

def node_answer(state: SQLAgentState) -> dict:
    template = read_prompt("sql_02_answer.md")
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    response = chain.invoke({
        "question": state["question"],
        "query": state["query"],
        "result": state["result"],
    })
    return {"response": response}

# ---------------------------------------------------------
# 그래프 빌드
# ---------------------------------------------------------
_sql_graph = None

def _get_sql_graph():
    global _sql_graph
    if _sql_graph is None:
        builder = StateGraph(SQLAgentState)
        builder.add_node("schema", node_schema)
        builder.add_node("sql_gen", node_sql_gen)
        builder.add_node("execute", node_execute)
        builder.add_node("answer", node_answer)
        builder.add_edge(START, "schema")
        builder.add_edge("schema", "sql_gen")
        builder.add_edge("sql_gen", "execute")
        builder.add_edge("execute", "answer")
        builder.add_edge("answer", END)
        _sql_graph = builder.compile()
    return _sql_graph

# ---------------------------------------------------------
# 외부 호출용 함수
# ---------------------------------------------------------
def get_sql_answer(question, username, allowed_views=None):
    try:
        if allowed_views is None:
            allowed_views = []
        print(f"\n🔍 [SQL Agent] 질문 분석: '{question}' (User: {username})")
        graph = _get_sql_graph()
        result = graph.invoke({
            "question": question,
            "username": username,
            "allowed_views": allowed_views,
        })
        return result.get("response", "응답을 생성하지 못했습니다.")
    except Exception as e:
        error_msg = f"데이터 조회 중 오류가 발생했습니다: {e}"
        print(f"❌ [SQL Agent Error]: {error_msg}")
        return error_msg

# --- 테스트 코드 ---
if __name__ == "__main__":
    test_views = ["account_summary_view", "transaction_history_view"]
    q = "내 월급통장 잔액이 얼마야?"
    print(f"Q: {q}")
    print(f"A: {get_sql_answer(q, 'test_user', test_views)}")
