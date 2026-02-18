import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from dotenv import load_dotenv

from utils.handle_sql import get_data

# 1. 환경 변수 로드
load_dotenv()

# 2. LLM 설정
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

def get_schema_info(allowed_views: list):
    try:
        schema_text = ""

        for view_name in allowed_views:
            schema_text += f"\n[View: {view_name}]\n"

            columns = get_data(f"DESCRIBE {view_name}")
            for col in columns:
                schema_text += f"- {col['Field']} ({col['Type']})\n"

        return schema_text.strip()

    except Exception as e:
        return f"스키마 조회 실패: {e}"


# --- SQL 청소 함수 (기존 유지) ---
def clean_sql_query(text: str) -> str:
    print(text)
    text = text.strip()
    if text.startswith("SQLQuery:"):
        text = text.replace("SQLQuery:", "").strip()
    if "```" in text:
        parts = text.split("```")
        # 백틱이 여러 개일 경우를 대비해 가장 긴 내용을 코드 블록으로 간주하거나, sql 태그 확인
        for part in parts:
            if part.lower().strip().startswith("sql"):
                text = part.strip()[3:].strip()
                break
            elif len(part) > 20 and "select" in part.lower(): # 간단한 휴리스틱
                text = part.strip()
    return text.strip()

# --- [변경] 쿼리 실행 래퍼 함수 ---
def run_db_query(query, username):
    try:
        # handle_sql의 get_data 사용 (결과는 딕셔너리 리스트)
        result = get_data(query)
        if not result:
            return "검색 결과가 없습니다."
        return str(result) # LLM에게 텍스트로 전달하기 위해 문자열 변환
    except Exception as e:
        return f"SQL 실행 오류: {e}"

# 3. 프롬프트 정의

# (1) Text-to-SQL 프롬프트
# 스키마 정보를 동적으로 주입받습니다.
sql_gen_template = """
You are a MySQL expert. 
Based on the provided database schema, write a SQL query to answer the user's question.

[Schema]
{schema}

[Rules]
1. Output ONLY the SQL query. 
2. Do not explain anything.
3. Use CURDATE() for 'today' or 'recent'.

Question: {question}
SQL Query:
"""
sql_gen_prompt = PromptTemplate.from_template(sql_gen_template)

# (2) 최종 답변 프롬프트 (기존 유지)
answer_template = """
Given the following user question, corresponding SQL query, and SQL result, answer the user question.

[Rules]
1. You MUST use the **actual values** from the [SQL Result].
2. If there are multiple records, list them with bullet points.
3. Format numbers with commas (e.g., 15,000원).
4. Answer in Korean naturally.

Question: {question}
SQL Query: {query}
SQL Result: {result}
Answer: 
"""
answer_prompt = PromptTemplate.from_template(answer_template)

# 4. 전체 파이프라인 연결 (Chain)

# Step 1: SQL 생성 체인
sql_chain = (
    RunnablePassthrough.assign(schema=lambda x: get_schema_info(x["allowed_views"])) 
    | sql_gen_prompt 
    | llm 
    | StrOutputParser() 
    | clean_sql_query
)

# Step 2: 전체 응답 체인
full_chain = (
    RunnablePassthrough.assign(query=sql_chain)
    .assign(result=lambda x: run_db_query(x["query"], x["username"]))
    | answer_prompt
    | llm
    | StrOutputParser()
)

# --- 외부 호출용 함수 ---
def get_sql_answer(question, username, allowed_views):
    try:
        response = full_chain.invoke({
            "question": question, 
            "username": username,
            "allowed_views": allowed_views
            })
        return response
    except Exception as e:
        return f"데이터 조회 중 오류가 발생했습니다: {e}"

if __name__ == "__main__":
    print(f"Q: 내 월급통장 잔액이 얼마야?")
    print(f"A: {get_sql_answer('내 월급통장 잔액이 얼마야?')}")