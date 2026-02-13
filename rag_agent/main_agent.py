import os
import json
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
# [중요] 최신 버전에 맞게 classic 사용 (환경에 따라 community일 수도 있음)
from langchain_classic.memory import ConversationSummaryMemory 

# 우리가 만든 두 전문가(모듈)
from rag_agent.sql_agent import get_sql_answer
from rag_agent.finrag_agent import get_rag_answer

# 환경 변수 로드
load_dotenv()

# LLM 설정 (똑똑한 모델 추천)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# 메모리 초기화
memory = ConversationSummaryMemory(llm=llm)

# ---------------------------------------------------------
# 1. 언어 감지 및 한국어 번역 체인
# ---------------------------------------------------------
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
# [UPGRADE] 1.5. 문맥 보정(Refinement) 체인 - 프롬프트 강화
# ---------------------------------------------------------
# 단순히 "rephrase" 하라고 하면 "2번"을 그대로 둡니다.
# "지시어(Demonstrative pronouns)"와 "순서(Ordinals)"를 해결하라고 명시해야 합니다.
refinement_template = """
You are a 'Context Resolver' for a financial AI.
Your goal is to rewrite the 'Follow-up Question' into a 'Standalone Question' that can be understood without the chat history.

[Context (Summary of previous conversation)]
{history}

[Current Follow-up Question]
{question}

[Instructions]
1. If the user uses pronouns like "that", "it", "the previous one" (그거, 아까 말한 거), replace them with the specific noun from the Context.
2. If the user refers to a list item like "Number 2", "The second one" (2번, 두 번째), identify what the second item was in the Context and replace it.
3. If the question is already clear, output it exactly as is.
4. Output ONLY the rewritten question in Korean. Do not explain.

[Example]
Context: The AI explained 'Spread', 'Interest Rate Futures', and 'Fixed Rate'.
Question: Tell me more about the second one.
Rewritten: 금리선물에 대해 더 자세히 알려줘.

Standalone Question (Korean):
"""
refinement_prompt = PromptTemplate.from_template(refinement_template)
refinement_chain = refinement_prompt | llm | StrOutputParser()


# ---------------------------------------------------------
# [UPGRADE] 2. 의도 분류 체인 (Router) - GENERAL 추가
# ---------------------------------------------------------
router_template = """
Given the user's question (in Korean), classify it into one of the three categories: 'DATABASE', 'KNOWLEDGE', or 'GENERAL'.

[Definitions]
- **DATABASE**: User asks about *personal* data. (e.g., "내 잔액 얼마?", "거래 내역 보여줘", "얼마 썼어?")
- **KNOWLEDGE**: User asks about *financial concepts*, definitions, or products. (e.g., "가산금리가 뭐야?", "적금 추천", "환율 알려줘")
- **GENERAL**: Greetings, thanks, closing remarks, or simple small talk NOT related to finance. (e.g., "안녕", "고마워", "넌 누구니?", "방가방가")

[Rule]
- Output ONLY one word: 'DATABASE', 'KNOWLEDGE', or 'GENERAL'.

Question: {question}
Category:
"""
router_prompt = PromptTemplate.from_template(router_template)
router_chain = router_prompt | llm | StrOutputParser()


# ---------------------------------------------------------
# [NEW] 2.5 일상 대화(General) 처리 체인
# ---------------------------------------------------------
general_template = """
You are a friendly and polite Financial AI Assistant named 'FinBot'.
The user said: "{question}"

Please respond naturally and politely in Korean.
If the user greets you, greet them back and ask how you can help with their financial questions.
If they say thanks, say "You're welcome."

Response:
"""
general_prompt = PromptTemplate.from_template(general_template)
general_chain = general_prompt | llm | StrOutputParser()


# ---------------------------------------------------------
# 3. 최종 답변 역번역 체인
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
        trans_result_str = translation_chain.invoke({"question": question}).strip()
        trans_result_str = trans_result_str.replace("```json", "").replace("```", "")
        trans_result = json.loads(trans_result_str)
        
        source_lang = trans_result.get("source_language", "Korean")
        korean_query = trans_result.get("korean_query", question)
        
        print(f"🌐 [Translator] 감지된 언어: {source_lang} -> 변환된 질문: {korean_query}")
        
    except Exception as e:
        print(f"⚠️ 번역 오류 발생: {e}")
        source_lang = "Korean"
        korean_query = question

    # --- Step 1.5: 메모리를 활용한 질문 구체화 (Refinement) ---
    history = memory.load_memory_variables({})['history']
    refined_query = korean_query # 기본값
    
    # 메모리가 있을 때만 Refinement 수행
    if history:
        # 일상적인 인사("안녕") 같은 짧은 말은 Refinement를 거치면 오히려 이상해질 수 있으나,
        # 문맥 파악을 위해 일단 수행하되, Router에서 GENERAL로 빠지면 괜찮습니다.
        print(f"🧠 [Memory Summary]: {history}")
        
        refined_query = refinement_chain.invoke({
            "history": history,
            "question": korean_query
        }).strip()
        
        if refined_query != korean_query:
            print(f"✨ [Refinement] '{korean_query}' -> '{refined_query}'")

    # --- Step 2: 의도 파악 (Router) ---
    category = router_chain.invoke({"question": refined_query}).strip()
    # 혹시 모를 특수문자 제거
    category = category.replace("'", "").replace('"', "")
    
    print(f"🕵️ [Router] 의도 분석 결과: [{category}]")
    
    korean_answer = ""
    
    # --- Step 3: 전문가 호출 (Agent Execution) ---
    if category == "DATABASE":
        print("\n=== 🏦 SQL Agent 호출 ===")
        korean_answer = get_sql_answer(refined_query)
        print("=== 🏦 SQL Agent 종료 ===\n")
        
    elif category == "KNOWLEDGE":
        print("\n=== 🎓 FinRAG Agent 호출 ===")
        # [중요] RAG에게는 '정제된 질문(refined_query)'을 던져야 정확도가 올라갑니다.
        # 하지만 출력용 'original_query'는 사용자 원본을 유지합니다.
        korean_answer = get_rag_answer(refined_query, original_query=question)
        print("=== 🎓 FinRAG Agent 종료 ===\n")
        
    elif category == "GENERAL":
        print("\n=== 💬 General Chat 호출 ===")
        korean_answer = general_chain.invoke({"question": korean_query})
        print("=== 💬 General Chat 종료 ===\n")
        
    else:
        # Fallback
        korean_answer = "죄송해요, 제가 이해하기 어려운 질문이네요. 금융 정보나 개인 자산에 대해 물어봐 주세요."
        print(f"❌ [Exception] 처리 불가 카테고리: {category}")

    # --- Step 3.5: 대화 내용 메모리에 저장 ---
    # 중요: 저장할 때는 '정제된 질문'과 '답변'을 저장해야 다음 요약이 정확해집니다.
    memory.save_context(
        {"input": refined_query}, 
        {"output": korean_answer}
    )

    # --- Step 4: 최종 답변 구성 (발표 및 시연용) ---
    if "Korean" not in source_lang and "한국어" not in source_lang:
        print(f"🔄 [Translator] 시연을 위한 한국어 번역본 생성 중...")
        
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


# --- 실행 테스트 ---
if __name__ == "__main__":
    while True:
        q = input("\n질문을 입력하세요 (exit to quit): ")
        if q.lower() in ["exit", "quit"]:
            break
        
        answer = run_fintech_agent(q)
        print(f"\n📢 [Final Answer]: {answer}")
        print("-" * 50)