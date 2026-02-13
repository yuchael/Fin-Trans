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

# --- [추가] 동적 스키마 조회 함수 ---
# LangChain의 SQLDatabase 대신, 직접 현재 DB의 테이블 정보를 문자열로 만들어줍니다.
def get_schema_info():
    try:
        # 테이블 목록 조회
        tables = get_data("SHOW TABLES")
        schema_text = ""
        
        for table in tables:
            # 딕셔너리 값 중 첫 번째가 테이블 이름 (Key는 'Tables_in_dbName' 등으로 가변적)
            table_name = list(table.values())[0]
            schema_text += f"\n[Table: {table_name}]\n"
            
            # 컬럼 정보 조회
            columns = get_data(f"DESCRIBE {table_name}")
            for col in columns:
                # Field(컬럼명), Type(타입) 정보만 추출
                schema_text += f"- {col['Field']} ({col['Type']})\n"
                
        return schema_text.strip()
    except Exception as e:
        return f"스키마 조회 실패: {e}"

# --- SQL 청소 함수 (기존 유지) ---
def clean_sql_query(text: str) -> str:
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
def run_db_query(query):
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

# 스키마는 실행 시점에 한 번 로딩하여 컨텍스트에 고정하거나, 매번 로딩할 수 있습니다.
# 여기서는 매 호출마다 최신 스키마를 반영하도록 lambda 사용 가능하지만,
# 성능을 위해 전역 변수처럼 처리하거나 RunnableLambda로 감쌀 수 있습니다.
# 간단하게 chain 구성 시점에 가져오도록 합니다 (DB 구조가 자주 안 바뀐다고 가정).
current_schema = get_schema_info()

# Step 1: SQL 생성 체인
sql_chain = (
    RunnablePassthrough.assign(schema=lambda x: current_schema) 
    | sql_gen_prompt 
    | llm 
    | StrOutputParser() 
    | clean_sql_query
)

# Step 2: 전체 응답 체인
full_chain = (
    RunnablePassthrough.assign(query=sql_chain)
    .assign(result=lambda x: run_db_query(x["query"]))
    | answer_prompt
    | llm
    | StrOutputParser()
)

# --- 외부 호출용 함수 ---
def get_sql_answer(question):
    try:
        print(f"\n🔍 [SQL Agent] 질문 분석 시작: {question}")

        # 1. SQL 생성
        generated_sql = sql_chain.invoke({"question": question})
        print(f"📝 [Generated SQL]: {generated_sql}")  # <--- SQL 출력 추가

        # 2. DB 조회
        sql_result = run_db_query(generated_sql)
        print(f"📊 [SQL Result]: {sql_result}")       # <--- 조회 결과 출력 추가

        # 3. 최종 답변 생성
        final_response = full_chain.invoke({
            "question": question,
            "query": generated_sql,
            "result": sql_result
        })
        
        print(f"💬 [SQL Answer]: {final_response}")   # <--- 최종 답변 출력 추가
        return final_response

    except Exception as e:
        error_msg = f"데이터 조회 중 오류가 발생했습니다: {e}"
        print(f"❌ [Error]: {error_msg}")
        return error_msg

if __name__ == "__main__":
    print(f"Schema Info Check:\n{current_schema}\n")
    print("-" * 50)
    print(f"Q: 내 월급통장 잔액이 얼마야?")
    print(f"A: {get_sql_answer('내 월급통장 잔액이 얼마야?')}")