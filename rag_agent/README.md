# 🧠 AI Financial Agent Module (RAG + SQL)

## 📌 파트 소개 (My Role)
단순한 룰 기반 챗봇이 아닌, **LLM(Large Language Model)**을 활용한 하이브리드 에이전트를 구축했습니다. 이 에이전트는 사용자의 질문 의도를 파악하여 **개인 금융 데이터 조회(SQL)**와 **금융 지식 검색(RAG)**을 유동적으로 전환하며 수행합니다.

### 💡 핵심 구현 기능
1. **Hybrid Query Routing**: 질문이 "내 잔액"에 관한 것인지, "용어 설명"에 관한 것인지 판단하여 분기 처리.
2. **Text-to-SQL (Personal Data)**: 자연어를 SQL 쿼리로 변환하여 DB에서 실시간 개인 정보 조회.
3. **RAG (Knowledge Base)**: 금융 용어 PDF 데이터를 벡터화하여 DB에 구축하고, 유사도 검색을 통해 정확한 용어 설명 제공.

---

## 📂 핵심 파일 및 역할 설명

이 모듈을 구성하는 주요 파일들의 역할은 다음과 같습니다.

| 파일명 | 분류 | 핵심 역할 및 기능 |
| :--- | :---: | :--- |
| **`main_agent.py`** | **Control** | **[지휘자]** 전체 챗봇의 메인 엔트리 포인트.<br>사용자 질문의 의도를 `DATABASE`(개인정보)와 `KNOWLEDGE`(지식)로 분류하고, 적절한 하위 에이전트(`sql_agent` 또는 `chatbot`)를 호출합니다. |
| **`sql_agent.py`** | **Agent** | **[은행원]** 개인 금융 데이터 조회 담당.<br>LangChain의 SQL Toolkit을 활용해 자연어를 SQL로 변환, 실행, 결과 해석까지 수행합니다. (예: 잔액 조회, 거래 내역 확인) |
| **`chatbot.py`** | **Agent** | **[금융 교수]** 금융 지식 설명 담당 (RAG).<br>MySQL에 저장된 벡터 데이터를 코사인 유사도로 검색하여, 질문과 가장 연관된 금융 용어를 찾아 설명합니다. 다국어 답변이 가능합니다. |
| **`pdf_to_mysql.py`** | **ETL** | **[데이터 추출]** 원본 `economic_terms.pdf` 파일에서 금융 용어와 정의를 텍스트로 추출하여 MySQL `terms` 테이블에 적재합니다. |
| **`mysql_to_vector.py`** | **ETL** | **[임베딩 구축]** DB에 저장된 텍스트 데이터를 OpenAI Embedding API를 통해 벡터(숫자)로 변환하고, 이를 다시 DB에 저장하여 검색 가능한 상태로 만듭니다. |

---

## ⚙️ 실행 흐름 (Workflow)



1. **User**: "내 월급통장 잔액 얼마야?"
2. **Router (`main_agent.py`)**: 질문 분석 → `DATABASE` 카테고리로 판단.
3. **SQL Agent (`sql_agent.py`)**: 
   - SQL 생성: `SELECT balance FROM accounts WHERE alias='월급통장'...`
   - DB 조회: 결과 `5,000,000` 반환.
4. **Answer**: "현재 월급통장 잔액은 5,000,000원입니다."

---
