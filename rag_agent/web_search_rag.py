import os
from pathlib import Path
from dotenv import load_dotenv
from tavily import TavilyClient

# LangChain Imports
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 1. 환경 설정
load_dotenv()

# LLM 설정 (일관성을 위해 ChatOpenAI 사용)
llm = ChatOpenAI(model="gpt-5-mini")

# ---------------------------------------------------------
# [설정] 프롬프트 경로 설정 및 로딩 함수
# ---------------------------------------------------------
# rag_agent/web_search_rag.py 위치 기준
CURRENT_DIR = Path(__file__).resolve().parent
PROMPT_DIR = CURRENT_DIR / "prompt" / "web_search"

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
# 체인 구성: 웹 검색 답변 생성
# ---------------------------------------------------------
web_search_template = read_prompt("web_search_01_response.md")
web_search_prompt = PromptTemplate.from_template(web_search_template)

# 체인 생성 (Prompt -> LLM -> String)
web_search_chain = (
    web_search_prompt
    | llm
    | StrOutputParser()
)

class WebSearchRAG:
    def __init__(self):
        # Tavily API 키 확인
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        if not tavily_api_key:
            print("⚠️ [Warning] TAVILY_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        
        self.tavily = TavilyClient(api_key=tavily_api_key)
    
    def web_search(self, query):
        """실시간 웹 검색 및 답변 생성"""
        print(f"🔎 [Web Search] 검색 시작: {query}")
        
        try:
            # 1. Tavily 검색 실행 (상위 3개 결과)
            search_results = self.tavily.search(query, max_results=3)
            
            # 2. 컨텍스트 포맷팅 (프롬프트 주입용)
            context_parts = []
            sources = []
            
            for i, result in enumerate(search_results.get('results', []), 1):
                title = result.get('title', 'No Title')
                url = result.get('url', '#')
                content = result.get('content', '')
                
                # 프롬프트에 들어갈 텍스트 구성
                context_parts.append(f"=== [Source {i}] {title} ===\nURL: {url}\nContent: {content}\n")
                
                # 메타데이터 저장 (UI 표시용)
                sources.append({'title': title, 'url': url})
            
            context_str = "\n".join(context_parts)
            
            if not context_str:
                return {
                    'answer': "검색 결과가 없습니다.",
                    'sources': [],
                    'source_type': 'Web Search'
                }
            
            # 3. LLM 답변 생성 (LangChain Chain 사용)
            answer = web_search_chain.invoke({
                "question": query,
                "context": context_str
            })
            
            return {
                'answer': answer,
                'sources': sources,
                'source_type': 'Web Search'
            }
            
        except Exception as e:
            print(f"❌ [Web Search Error]: {e}")
            return {
                'answer': "죄송합니다. 웹 검색 중 오류가 발생했습니다.",
                'sources': [],
                'source_type': 'Error'
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
    for src in result['sources']:
        print(f" - {src['title']} ({src['url']})")