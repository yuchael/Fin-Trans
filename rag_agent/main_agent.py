import os
import json  # [수정] json 모듈 임포트 추가
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 우리가 만든 두 전문가(모듈)를 불러옵니다.
from rag_agent.sql_agent import get_sql_answer
from rag_agent.finrag_agent import get_rag_answer

# 환경 변수 로드
load_dotenv()

# LLM 설정
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# ---------------------------------------------------------
# 1. 언어 감지 및 한국어 번역 체인
# ---------------------------------------------------------
# [수정 포인트] JSON 예시의 중괄호 {}를 {{ }}로 변경하여 이스케이프 처리함
translation_template = """
You are a professional translator for a financial AI assistant.
Your task is to analyze the User's Input and:
1. Identify the language of the input (e.g., English, Vietnamese, Korean).
2. Translate the input into natural **Korean** (if it's not already Korean).

Output format must be a raw JSON object:
{{
    "source_language": "Detected Language",
    "korean_query": "Translated Korean Text"
}}

User Input: {question}
JSON Output:
"""
translation_prompt = PromptTemplate.from_template(translation_template)
translation_chain = translation_prompt | llm | StrOutputParser()


# ---------------------------------------------------------
# 2. 의도 분류 체인 (Router)
# ---------------------------------------------------------
router_template = """
Given the user's question (in Korean), classify it into one of the two categories: 'DATABASE' or 'KNOWLEDGE'.

[Definitions]
- **DATABASE**: 개인 금융 데이터, 계좌 잔액, 거래 내역, 이체 기록 등 나만의 정보 조회. (예: "내 잔액 얼마야?", "어제 얼마 썼어?")
- **KNOWLEDGE**: 일반적인 금융 용어, 경제 개념, 정의, 은행 업무 절차 등 지식 검색. (예: "인플레이션이 뭐야?", "SWIFT 코드가 뭐야?", "적금 추천해줘")

[Rule]
- Output ONLY one word: 'DATABASE' or 'KNOWLEDGE'.
- Do not add any explanation.

Question: {question}
Category:
"""
router_prompt = PromptTemplate.from_template(router_template)
router_chain = router_prompt | llm | StrOutputParser()


# ---------------------------------------------------------
# 3. 최종 답변 역번역 체인 (한국어 -> 사용자 언어)
# ---------------------------------------------------------
re_translation_template = """
You are a professional translator.
Translate the following Korean Answer into {target_language} naturally.
Maintain the tone of a polite financial assistant.

Korean Answer: {korean_answer}
Translated Answer:
"""
re_translation_prompt = PromptTemplate.from_template(re_translation_template)
re_translation_chain = re_translation_prompt | llm | StrOutputParser()


# ---------------------------------------------------------
# 4. 메인 에이전트 실행 함수
# ---------------------------------------------------------
def run_fintech_agent(question):
    print(f"\n[User Input]: {question}")
    
    # --- Step 1: 언어 감지 및 한국어 번역 ---
    try:
        # JSON 형태의 문자열을 받아서 파싱
        trans_result_str = translation_chain.invoke({"question": question}).strip()
        # 혹시 모를 마크다운('''json ... ''') 제거 처리
        trans_result_str = trans_result_str.replace("```json", "").replace("```", "")
        trans_result = json.loads(trans_result_str)
        
        source_lang = trans_result.get("source_language", "Korean")
        korean_query = trans_result.get("korean_query", question)
        
        print(f"🌐 [Translator] 감지된 언어: {source_lang} -> 변환된 질문: {korean_query}")
        
    except Exception as e:
        print(f"⚠️ 번역 오류 발생: {e}")
        # 오류 시 기본값 설정 (한국어로 가정)
        source_lang = "Korean"
        korean_query = question

    # --- Step 2: 의도 파악 (Router) ---
    # 번역된 'korean_query'를 라우터에 넣습니다.
    category = router_chain.invoke({"question": korean_query}).strip()
    print(f"🕵️ [Router] 의도 분석 결과: [{category}]")
    
    korean_answer = ""
    
    # --- Step 3: 전문가 호출 (Agent Execution) ---
    if category == "DATABASE":
        print("🏦 [System] 은행 직원(SQL Agent) 연결 중...")
        korean_answer = get_sql_answer(korean_query)
        
    elif category == "KNOWLEDGE":
        print("🎓 [System] 금융 교수(FinRAG Agent) 연결 중...")
        korean_answer = get_rag_answer(korean_query)
    
    else:
        korean_answer = "죄송합니다. 질문의 의도를 파악하지 못했습니다."

    print(f"🤖 [Internal Answer (KR)]: {korean_answer}")

    # --- Step 4: 최종 답변 역번역 (Output Translation) ---
    # 사용자가 한국인이 아니면 답변을 번역해서 줍니다.
    if "Korean" not in source_lang and "한국어" not in source_lang:
        print(f"🔄 [Translator] 답변을 {source_lang}(으)로 번역 중...")
        final_answer = re_translation_chain.invoke({
            "target_language": source_lang, 
            "korean_answer": korean_answer
        })
    else:
        # 한국어 사용자라면 그대로 출력
        final_answer = korean_answer

    return final_answer


# --- 실행 테스트 ---
if __name__ == "__main__":
    while True:
        q = input("\n질문을 입력하세요 (exit to quit): ")
        if q.lower() in ["exit", "quit"]:
            break
        
        answer = run_fintech_agent(q)
        print(f"\n📢 [Final Answer]: {answer}")
        print("-" * 50)