import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain.chains import create_sql_query_chain
from langchain_community.tools import QuerySQLDatabaseTool
from operator import itemgetter
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough

# 1. 환경 변수 로드
load_dotenv()

# 2. DB 연결
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = "fintech_agent" # 팀원 DB 이름

db_uri = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
db = SQLDatabase.from_uri(db_uri)

# 3. LLM 설정
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# --- [추가된 부분] SQL 청소 함수 ---
def clean_sql_query(text: str) -> str:
    """LLM이 뱉은 SQL에서 불필요한 마크다운이나 접두어를 제거합니다."""
    text = text.strip()
    # "SQLQuery:" 접두어 제거
    if text.startswith("SQLQuery:"):
        text = text.replace("SQLQuery:", "").strip()
    # 마크다운 코드 블록 제거 (```sql ... ```)
    if "```" in text:
        text = text.split("```")[1] # 백틱 내부 추출
        if text.lower().startswith("sql"):
            text = text[3:] # 'sql' 글자 제거
    return text.strip()

# 4. Text-to-SQL 체인 생성
generate_query = create_sql_query_chain(llm, db)
execute_query = QuerySQLDatabaseTool(db=db)

# 최종 답변 프롬프트
answer_prompt = PromptTemplate.from_template(
    """Given the following user question, corresponding SQL query, and SQL result, answer the user question.

    [Rules]
    1. You MUST use the **actual values** from the [SQL Result].
    2. Do NOT use placeholders like "[SQL Result]" or "provided data".
    3. If there are multiple records, list them with bullet points.
    4. Format numbers with commas (e.g., 15,000원) and convert dates to a readable format.
    5. Answer in Korean naturally.

    Question: {question}
    SQL Query: {query}
    SQL Result: {result}
    Answer: """
)

# 5. 전체 파이프라인 연결 (Chain)
# 핵심 변경점: generate_query 뒤에 | clean_sql_query 를 붙였습니다.
chain = (
    RunnablePassthrough.assign(query=generate_query | clean_sql_query).assign(
        result=itemgetter("query") | execute_query
    )
    | answer_prompt
    | llm
    | StrOutputParser()
)

# --- 테스트 실행 함수 ---
def get_sql_answer(question):
    try:
        # chain을 실행해서 결과(문자열)를 얻음
        response = chain.invoke({"question": question})
        return response
    except Exception as e:
        # 에러가 나면 에러 메시지를 리턴
        return f"데이터 조회 중 오류가 발생했습니다: {e}"

# --- 외부 호출용 함수 ---
def get_sql_answer(question):
    try:
        # chain을 실행해서 결과(문자열)를 얻음
        response = chain.invoke({"question": question})
        return response
    except Exception as e:
        # 에러가 나면 에러 메시지를 리턴
        return f"데이터 조회 중 오류가 발생했습니다: {e}"

# --- 단독 실행 시 테스트 ---
if __name__ == "__main__":
    # print()를 붙여야 리턴된 값을 화면에 출력합니다.
    print(f"결과 1: {get_sql_answer('내 월급통장 잔액이 얼마야?')}")
    print(f"결과 2: {get_sql_answer('최근에 식비로 얼마 썼어?')}")
    print(f"결과 3: {get_sql_answer('가입된 사용자가 총 몇 명이야?')}")