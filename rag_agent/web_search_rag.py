import os
from pathlib import Path
from typing import TypedDict
from dotenv import load_dotenv
from tavily import TavilyClient

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# ---------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
PROMPT_DIR = CURRENT_DIR / "prompt" / "web_search"

def read_prompt(filename: str) -> str:
    file_path = PROMPT_DIR / filename
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"❌ [Error] 프롬프트 파일을 찾을 수 없습니다: {file_path}")
        return ""

# ---------------------------------------------------------
# [LangGraph] 웹 검색 상태
# ---------------------------------------------------------
class WebSearchState(TypedDict, total=False):
    question: str
    context: str
    sources: list
    answer: str

# ---------------------------------------------------------
# [LangGraph] 노드
# ---------------------------------------------------------
def node_answer(state: WebSearchState) -> dict:
    template = read_prompt("web_search_01_response.md")
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    answer = chain.invoke({"question": state["question"], "context": state.get("context", "")})
    return {"answer": answer}

# 그래프: search 결과가 이미 state에 있으므로, answer 노드만 있으면 됨.
# 검색은 클래스 내부에서 하고, context/sources를 state에 넣은 뒤 그래프 호출
def _build_web_search_graph():
    builder = StateGraph(WebSearchState)
    builder.add_node("answer", node_answer)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    return builder.compile()

_web_search_graph = None

def _get_web_search_graph():
    global _web_search_graph
    if _web_search_graph is None:
        _web_search_graph = _build_web_search_graph()
    return _web_search_graph

# ---------------------------------------------------------
# WebSearchRAG 클래스 (LangGraph 사용)
# ---------------------------------------------------------
class WebSearchRAG:
    def __init__(self):
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        if not tavily_api_key:
            print("⚠️ [Warning] TAVILY_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        self.tavily = TavilyClient(api_key=tavily_api_key)

    def web_search(self, query):
        """실시간 웹 검색 및 답변 생성 (LangGraph)"""
        print(f"🔎 [Web Search] 검색 시작: {query}")
        try:
            search_results = self.tavily.search(query, max_results=3)
            context_parts = []
            sources = []
            for i, result in enumerate(search_results.get("results", []), 1):
                title = result.get("title", "No Title")
                url = result.get("url", "#")
                content = result.get("content", "")
                context_parts.append(f"=== [Source {i}] {title} ===\nURL: {url}\nContent: {content}\n")
                sources.append({"title": title, "url": url})
            context_str = "\n".join(context_parts)

            if not context_str:
                return {"answer": "검색 결과가 없습니다.", "sources": [], "source_type": "Web Search"}

            graph = _get_web_search_graph()
            result_state = graph.invoke({"question": query, "context": context_str, "sources": sources})
            answer = result_state.get("answer", "답변 생성 실패")

            return {
                "answer": answer,
                "sources": sources,
                "source_type": "Web Search",
            }
        except Exception as e:
            print(f"❌ [Web Search Error]: {e}")
            return {
                "answer": "죄송합니다. 웹 검색 중 오류가 발생했습니다.",
                "sources": [],
                "source_type": "Error",
            }

# --- 테스트 코드 ---
if __name__ == "__main__":
    rag = WebSearchRAG()
    q = "현재 삼성전자 주가는?"
    result = rag.web_search(q)
    print(f"\n{'='*80}")
    print(f"📝 질문: {q}")
    print(f"{'='*80}\n")
    print(f"💡 답변:\n{result['answer']}\n")
    print(f"📚 출처:")
    for src in result["sources"]:
        print(f" - {src['title']} ({src['url']})")
