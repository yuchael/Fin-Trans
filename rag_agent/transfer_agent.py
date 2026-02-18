import os
import json
from pathlib import Path
from typing import TypedDict, List
from dotenv import load_dotenv
import bcrypt

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END

# 사용자 원본 코드의 유틸리티 (DB 핸들러가 있다고 가정)
from utils.handle_sql import get_data, execute_query

# 1. 환경 설정
load_dotenv()
# 온도가 0이어야 추출 및 매칭이 일관적입니다.
llm = ChatOpenAI(model="gpt-5-mini") 

# ---------------------------------------------------------
# [설정] 프롬프트 경로 (필요 시 유지, 여기서는 코드 내장 프롬프트 사용)
# ---------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------
# [LangGraph] 송금 정보 추출 그래프
# ---------------------------------------------------------
class TransferExtractState(TypedDict):
    question: str
    raw_llm_output: str
    extracted: dict

def _parse_transfer_json(text: str) -> dict:
    """JSON 파싱 및 예외 처리"""
    try:
        # 마크다운 코드 블록 제거
        text = text.strip().replace("```json", "").replace("```", "")
        return json.loads(text)
    except Exception as e:
        print(f"JSON Parsing Error: {e}, Raw: {text}")
        return {"target": None, "amount": None, "currency": None}

def _node_extract(state: TransferExtractState) -> dict:
    """
    사용자 발화에서 송금 대상, 금액, 통화를 추출합니다.
    (수정됨: '만원' 등의 단위 처리를 위한 강력한 프롬프트 적용)
    """
    
    # 한국어 금액 단위 처리 및 JSON 강제 프롬프트
    template = """
    You are a banking AI assistant. Extract transfer details from the user's input.
    
    # Extraction Rules
    1. **target**: Who receives the money? (Name or Relationship)
    2. **amount**: Convert Korean currency units to **Integer**. 반올림 하지 마.
       - '만 원', '만원' -> 10000
       - '천 원' -> 1000
       - '10만 원' -> 100000
    3. **currency**: Currency code (KRW, USD, etc). Default is "KRW".
       - "동" -> VND
       - "달러" -> USD
       
    # Output Format
    Return ONLY a JSON object. Do not add any markdown formatting.
    {{
        "target": "string or null",
        "amount": int or null,
        "currency": "string or null"
    }}
    
    # User Input
    {question}
    """
    
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    
    raw = chain.invoke({"question": state["question"]})
    extracted = _parse_transfer_json(raw)
    
    print(f"🔹 [Extraction Result]: {extracted}")  # 디버깅용 출력
    return {"raw_llm_output": raw, "extracted": extracted}

_transfer_extract_graph = None

def _get_transfer_extract_graph():
    global _transfer_extract_graph
    if _transfer_extract_graph is None:
        builder = StateGraph(TransferExtractState)
        builder.add_node("extract", _node_extract)
        builder.add_edge(START, "extract")
        builder.add_edge("extract", END)
        _transfer_extract_graph = builder.compile()
    return _transfer_extract_graph

def _invoke_transfer_extract(question: str) -> dict:
    graph = _get_transfer_extract_graph()
    result = graph.invoke({"question": question})
    return result.get("extracted", {"target": None, "amount": None, "currency": None})

# ---------------------------------------------------------
# [New] LLM 기반 연락처 의미 매칭 함수
# ---------------------------------------------------------
def _find_best_match_contact_llm(user_input: str, contacts: List[dict]) -> str | None:
    """
    단순 문자열 비교 실패 시, LLM을 통해 의미적 매칭을 수행합니다.
    예: user_input="엄마", contacts=[{'contact_name': 'Mother'}] -> returns 'Mother'
    """
    if not contacts:
        return None

    # 후보 리스트 텍스트화
    candidates_str = "\n".join([
        f"- Name: {c['contact_name']} (Relationship: {c.get('relationship', 'N/A')})" 
        for c in contacts
    ])

    template = """
    Find the best matching 'Name' from the Candidate List for the User Input.
    Consider synonyms and relationships (e.g., Mom=Mother, Dad=Father, Boss=Manager).
    
    User Input: {user_input}
    
    Candidate List:
    {candidates}
    
    Task:
    1. If there is a clear match, return ONLY the exact 'Name'.
    2. If no reasonable match exists, return "NONE".
    """
    
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    
    try:
        matched_name = chain.invoke({"user_input": user_input, "candidates": candidates_str}).strip()
        
        # "NONE"이거나 이상한 문자열이 반환될 경우 처리
        if matched_name == "NONE":
            return None
        
        # LLM이 반환한 이름이 실제 리스트에 존재하는지 재검증 (환각 방지)
        for c in contacts:
            if c["contact_name"] == matched_name:
                return matched_name
        return None
        
    except Exception as e:
        print(f"⚠️ LLM Matching Error: {e}")
        return None

# ---------------------------------------------------------
# DB 검증 및 로직 함수들
# ---------------------------------------------------------

def get_member_id(username):
    query = f"SELECT user_id FROM members WHERE username = '{username}'"
    result = get_data(query)
    return result[0]["user_id"] if result else None

def get_contact(user_id, target):
    # target 이름으로 정확히 조회
    query = f"""
    SELECT contact_id, contact_name, relationship, target_currency_code
    FROM contacts
    WHERE user_id = {user_id}
    AND contact_name = '{target}'
    """
    result = get_data(query)
    return result[0] if result else None

def get_all_contacts(user_id):
    query = f"SELECT contact_name, relationship FROM contacts WHERE user_id = {user_id}"
    return get_data(query)

def resolve_contact_name(user_id, user_input):
    """
    사용자 입력을 바탕으로 정확한 DB 내 연락처 이름(contact_name)을 찾습니다.
    1. 정확한 이름 매칭
    2. 관계(relationship) 매칭
    3. LLM 의미 기반 매칭 (New)
    """
    contacts = get_all_contacts(user_id)
    if not contacts:
        return None
        
    user_input_clean = user_input.strip()
    user_input_lower = user_input_clean.lower()

    # 1. 1차 시도: 정확한 문자열 매칭 (Python Loop) - 속도 최우선
    for c in contacts:
        # 이름 비교
        if user_input_lower == c["contact_name"].lower():
            return c["contact_name"]
        # 관계 비교 (DB에 relationship 컬럼이 있는 경우)
        if c.get("relationship") and user_input_lower == str(c["relationship"]).lower():
            return c["contact_name"]
            
    # 2. 2차 시도: LLM을 이용한 의미론적 매칭 (엄마 -> Mother 해결)
    print(f"🔀 '{user_input}' 정확한 매칭 실패. LLM 매칭 시도...")
    matched_name = _find_best_match_contact_llm(user_input_clean, contacts)
    
    if matched_name:
        print(f"✅ LLM 매칭 성공: {user_input} -> {matched_name}")
        return matched_name

    return None

def get_primary_account(user_id):
    query = f"""
    SELECT account_id, balance, currency_code
    FROM accounts
    WHERE user_id = {user_id}
    AND is_primary = 1
    """
    result = get_data(query)
    return result[0] if result else None

def get_user_password(username):
    query = f"SELECT pin_code FROM members WHERE username = '{username}'"
    result = get_data(query)
    return result[0]["pin_code"] if result else None

def get_exchange_rate(currency):
    if currency == "KRW":
        return 1.0

    query = f"""
    SELECT send_rate
    FROM exchange_rates
    WHERE currency_code = '{currency}'
    ORDER BY reference_date DESC
    LIMIT 1
    """
    result = get_data(query)
    if not result:
        return None
    return float(result[0]["send_rate"])

def update_balance(account_id, new_balance):
    query = f"UPDATE accounts SET balance = {new_balance} WHERE account_id = {account_id}"
    execute_query(query)

def insert_ledger(
    account_id, contact_id, amount_krw, balance_after,
    exchange_rate, target_amount, target_currency
):
    query = f"""
    INSERT INTO ledger (
        account_id, contact_id, transaction_type, amount, balance_after,
        exchange_rate, target_amount, target_currency_code, description, category
    )
    VALUES (
        {account_id}, {contact_id}, 'TRANSFER', {-amount_krw}, {balance_after},
        {exchange_rate}, {target_amount}, '{target_currency}', '송금', '이체'
    )
    """
    execute_query(query)

# ---------------------------------------------------------
# 메인 송금 로직
# ---------------------------------------------------------

def process_transfer(question: str, username: str, context: dict | None = None):

    context = context or {}

    user_id = get_member_id(username)
    if not user_id:
        return {"status": "ERROR", "message": "사용자를 찾을 수 없습니다."}

    # --------------------------------------------------
    # 1. PIN Code 입력 단계
    # --------------------------------------------------
    if context.get("awaiting_password"):
        stored_pin = get_user_password(username)
        if not stored_pin:
            return {"status": "ERROR", "message": "사용자 정보를 찾을 수 없습니다."}

        if isinstance(stored_pin, str):
            stored_pin = stored_pin.encode('utf-8')

        # 패스워드 검증
        if bcrypt.checkpw(question.encode('utf-8'), stored_pin) == False:
            context["password_attempts"] = context.get("password_attempts", 0) + 1
            if context["password_attempts"] >= 5:
                return {"status": "FAIL", "message": "PIN Code 5회 오류. 송금 실패."}

            return {
                "status": "NEED_PASSWORD",
                "message": f"PIN Code 오류. 남은 기회: {5 - context['password_attempts']}",
                "context": context
            }

        # 송금 실행 (DB 업데이트)
        account = get_primary_account(user_id)
        # 중요: context["target"]은 이미 검증된 'contact_name'이어야 함
        contact = get_contact(user_id, context["target"]) 

        new_balance = float(account["balance"]) - context["amount_krw"]
        update_balance(account["account_id"], new_balance)

        insert_ledger(
            account["account_id"],
            contact["contact_id"],
            context["amount_krw"],
            new_balance,
            context["exchange_rate"],
            context["amount"],
            context["currency"]
        )

        return {"status": "SUCCESS", "message": f"송금이 완료되었습니다. (잔액: {int(new_balance):,}원)"}

    # --------------------------------------------------
    # 2. 확인 단계
    # --------------------------------------------------
    if context.get("awaiting_confirm"):
        yes_signals = ["__yes__", "y", "yes", "네", "응", "맞아"]
        no_signals  = ["__no__",  "n", "no", "아니", "취소"]

        answer = question.strip().lower()

        if answer in no_signals:
            return {"status": "CANCEL", "message": "송금이 취소되었습니다."}

        if answer not in yes_signals:
            return {
                "status": "CONFIRM",
                "message": context.get("confirm_message", "송금을 확인해주세요."),
                "context": context,
                "ui_type": "confirm_buttons"
            }

        context["awaiting_confirm"] = False
        context["awaiting_password"] = True
        context["password_attempts"] = 0

        return {
            "status": "NEED_PASSWORD",
            "message": "PIN Code를 입력해주세요.",
            "context": context
        }

    # --------------------------------------------------
    # 3. HITL (Human-in-the-Loop) - 부족 정보 보완
    # --------------------------------------------------
    if context.get("missing_field"):
        field = context["missing_field"]

        if field == "target":
            # [수정] 여기서도 향상된 resolve 로직 사용
            resolved = resolve_contact_name(user_id, question)
            if not resolved:
                return {
                    "status": "NEED_INFO",
                    "field": "target",
                    "message": "연락처를 찾을 수 없습니다. 정확한 이름을 입력해주세요.",
                    "context": context
                }
            context["target"] = resolved

        elif field == "amount":
            try:
                # 간단한 숫자 처리 (복잡한 건 LLM이 했어야 함)
                clean_amt = question.strip().replace(",", "").replace("원", "")
                context["amount"] = float(clean_amt)
            except:
                return {
                    "status": "NEED_INFO",
                    "field": "amount",
                    "message": "금액을 숫자로 입력해주세요.",
                    "context": context
                }

        elif field == "currency":
            context["currency"] = question.strip().upper()

        context.pop("missing_field")

    # --------------------------------------------------
    # 4. 최초 요청 (LangGraph 추출)
    # --------------------------------------------------
    if not context.get("target") and not context.get("amount"):
        info = _invoke_transfer_extract(question)
        context["target"]   = info.get("target")
        context["amount"]   = info.get("amount")
        context["currency"] = info.get("currency")

    target   = context.get("target")
    amount   = context.get("amount")
    currency = context.get("currency")

    # 대상 검증 및 해결
    if not target:
        context["missing_field"] = "target"
        return {
            "status": "NEED_INFO",
            "field": "target",
            "message": "송금할 대상을 입력해주세요.",
            "context": context
        }

    # [수정] LLM 매칭 포함된 함수 호출
    resolved = resolve_contact_name(user_id, target)
    if not resolved:
        context["missing_field"] = "target"
        return {
            "status": "NEED_INFO",
            "field": "target",
            "message": f"'{target}'님을 연락처에서 찾을 수 없습니다. 정확한 이름을 알려주세요.",
            "context": context
        }
    context["target"] = resolved  # DB에 있는 정확한 이름으로 갱신

    # 금액 검증
    if not amount:
        context["missing_field"] = "amount"
        return {
            "status": "NEED_INFO",
            "field": "amount",
            "message": "송금 금액을 입력해주세요.",
            "context": context
        }

    if not currency:
        context["currency"] = "KRW"
        currency = "KRW"

    # 환율 및 잔액 체크
    rate = get_exchange_rate(currency)
    if rate is None:
        return {"status": "ERROR", "message": f"{currency} 환율 정보를 찾을 수 없습니다."}

    account = get_primary_account(user_id)
    if not account:
        return {"status": "ERROR", "message": "주 계좌를 찾을 수 없습니다."}

    amount_krw = float(amount) * rate

    if amount_krw > float(account["balance"]):
        return {"status": "ERROR", "message": "잔액이 부족합니다."}

    confirm_message = f"{resolved}님에게 {int(amount):,} {currency} ({int(amount_krw):,}원) 송금하시겠습니까?"

    context.update({
        "target":           resolved,
        "amount":           float(amount),
        "currency":         currency,
        "amount_krw":       amount_krw,
        "exchange_rate":    rate,
        "awaiting_confirm": True,
        "confirm_message":  confirm_message,
    })

    return {
        "status":   "CONFIRM",
        "message":  confirm_message,
        "context":  context,
        "ui_type":  "confirm_buttons"
    }

# ---------------------------------------------------------
# 외부 호출 함수
# ---------------------------------------------------------
def get_transfer_answer(question, username, context=None):
    try:
        return process_transfer(question, username, context)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "ERROR", "message": f"시스템 오류가 발생했습니다: {e}"}

if __name__ == "__main__":
    print("Transfer Agent with Advanced Matching Ready")