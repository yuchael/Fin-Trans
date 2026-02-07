# 🏦 Fin-Trans: 다국어 금융 용어 RAG 시스템

금융 경제 용어 사전 데이터를 바탕으로 사용자의 질문에 답변하는 다국어 지원 챗봇 프로젝트입니다. PDF 데이터 추출부터 벡터 데이터베이스 구축, LLM 답변 생성까지의 파이프라인을 포함합니다.

---

## 🛠️ 시스템 아키텍처 및 진행 과정

본 프로젝트는 데이터의 흐름에 따라 3단계로 구성됩니다.

### 1. 데이터 추출 및 DB 적재 (`pdf_to_mysql.py`)
* **목적**: PDF 형식의 금융 용어 사전을 텍스트로 파싱하여 정형 데이터화합니다.
* **주요 기능**:
  - `PyPDF2`를 활용한 PDF 텍스트 추출
  - 용어와 설명을 분리하는 정제 로직 적용
  - MySQL 데이터베이스에 용어 레코드 저장

### 2. 임베딩 및 벡터 검색 구축 (`mysql_to_vector.py`)
* **목적**: MySQL에 저장된 텍스트 데이터를 AI가 이해할 수 있는 벡터(Vector) 형태로 변환합니다.
* **주요 기능**:
  - `Sentence-Transformers` 등을 활용한 텍스트 임베딩 생성
  - 고속 유사도 검색을 위한 Vector DB(예: FAISS, Chroma) 구축
  - 자연어 쿼리에 대응하는 관련 문서 검색 기능

### 3. RAG 기반 다국어 챗봇 (`chatbot.py`)
* **목적**: 사용자의 질문에 대해 가장 관련 있는 금융 지식을 검색하고, LLM을 통해 답변을 생성합니다.
* **주요 기능**:
  - **RAG (Retrieval-Augmented Generation)**: 검색된 지식을 바탕으로 답변의 정확도 향상
  - **다국어 지원**: 한국어 질문에 대해 영어, 일어 등 다양한 언어로 번역 및 답변 제공
  - `Streamlit` 또는 터미널 기반의 인터페이스 제공

---

## 🚀 시작하기

### 환경 설정
가상환경을 활성화한 후 필요한 라이브러리를 설치합니다.
```bash
# 가상환경 활성화 (본인의 경로에 맞게)
source fintrans/Scripts/activate  # Windows
# 또는
source fintrans/bin/activate      # Mac/Linux

# 필수 라이브러리 설치
pip install -r requirements.txt
