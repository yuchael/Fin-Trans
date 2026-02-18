import os
import json
from pathlib import Path
from typing import TypedDict
from dotenv import load_dotenv
import bcrypt

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, START, END

# 사용자 원본 코드의 유틸리티 (DB 핸들러)
from utils.handle_sql import get_data, execute_query

# 1. 환경 설정
load_dotenv()
llm = ChatOpenAI(model="gpt-5-mini")

# ---------------------------------------------------------
# [설정] 프롬프트 경로 설정 및 로딩 함수
# ---------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
PROMPT_DIR = CURRENT_DIR.parent / "rag_agent" / "prompt" / "transfer"

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
# [LangGraph] 송금 정보 추출 그래프
# ---------------------------------------------------------
class TransferExtractState(TypedDict):
    question: str
    raw_llm_output: str
    extracted: dict

def _parse_transfer_json(text: str) -> dict:
    try:
        text = text.strip().replace("```json", "").replace("```", "")
        return json.loads(text)
    except Exception:
        return {"target": None, "amount": None, "currency": None}

def _node_extract(state: TransferExtractState) -> dict:
    template = read_prompt("transfer_01_extract.md")
    prompt = PromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    raw = chain.invoke({"question": state["question"]})
    extracted = _parse_transfer_json(raw)
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

def parse_transfer_json(text: str):
    return _parse_transfer_json(text)

# ---------------------------------------------------------
# DB 검증 함수들
# ---------------------------------------------------------

def get_member_id(username):
    query = f"SELECT user_id FROM members WHERE username = '{username}'"
    result = get_data(query)
    return result[0]["user_id"] if result else None

def get_contact(user_id, target):
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
    contacts = get_all_contacts(user_id)
    user_input = user_input.strip().lower()

    for c in contacts:
        if user_input == c["contact_name"].lower():
            return c["contact_name"]
        if c.get("relationship") and user_input == c["relationship"].lower():
            return c["contact_name"]
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

        if bcrypt.checkpw(question.encode('utf-8'), stored_pin) == False:
            context["password_attempts"] = context.get("password_attempts", 0) + 1

            if context["password_attempts"] >= 5:
                return {"status": "FAIL", "message": "PIN Code 5회 오류. 송금 실패."}

            return {
                "status": "NEED_PASSWORD",
                "message": f"PIN Code 오류. 남은 기회: {5 - context['password_attempts']}",
                "context": context
            }

        # 송금 실행
        account = get_primary_account(user_id)
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
    # 2. 확인 단계 (버튼 신호 + 텍스트 입력 모두 처리)
    # --------------------------------------------------
    if context.get("awaiting_confirm"):
        yes_signals = ["__yes__", "y", "yes", "네", "응", "맞아"]
        no_signals  = ["__no__",  "n", "no", "아니", "취소"]

        answer = question.strip().lower()

        if answer in no_signals:
            return {"status": "CANCEL", "message": "송금이 취소되었습니다."}

        if answer not in yes_signals:
            # 알 수 없는 입력 → 버튼 다시 표시
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
    # 3. HITL 단계 (부족 정보 보완)
    # --------------------------------------------------
    if context.get("missing_field"):
        field = context["missing_field"]

        if field == "target":
            resolved = resolve_contact_name(user_id, question)
            if not resolved:
                return {
                    "status": "NEED_INFO",
                    "field": "target",
                    "message": "연락처에서 찾을 수 없습니다. 정확한 이름을 입력해주세요.",
                    "context": context
                }
            context["target"] = resolved

        elif field == "amount":
            try:
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
    if not context.get("target") and not context.get("amount") and not context.get("currency"):
        info = _invoke_transfer_extract(question)
        context["target"]   = info.get("target")
        context["amount"]   = info.get("amount")
        context["currency"] = info.get("currency")

    target   = context.get("target")
    amount   = context.get("amount")
    currency = context.get("currency")

    # 대상 추론 및 검증
    if not target:
        context["missing_field"] = "target"
        return {
            "status": "NEED_INFO",
            "field": "target",
            "message": "송금할 대상을 입력해주세요.",
            "context": context
        }

    resolved = resolve_contact_name(user_id, target)
    if not resolved:
        context["missing_field"] = "target"
        return {
            "status": "NEED_INFO",
            "field": "target",
            "message": "연락처에서 찾을 수 없습니다. 정확한 이름을 입력해주세요.",
            "context": context
        }
    context["target"] = resolved

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

    rate = get_exchange_rate(currency)
    if rate is None:
        return {
            "status": "ERROR",
            "message": f"{currency} 환율 정보를 찾을 수 없습니다."
        }

    account = get_primary_account(user_id)
    if not account:
        return {"status": "ERROR", "message": "주 계좌를 찾을 수 없습니다."}

    amount_krw = float(amount) * rate

    if amount_krw > float(account["balance"]):
        return {"status": "ERROR", "message": "잔액이 부족합니다."}

    confirm_message = f"{resolved}에게 {amount} {currency} ({round(amount_krw, 2)}원) 송금하시겠습니까?"

    context = {
        "target":           resolved,
        "amount":           float(amount),
        "currency":         currency,
        "amount_krw":       amount_krw,
        "exchange_rate":    rate,
        "awaiting_confirm": True,
        "confirm_message":  confirm_message,   # ← 재표시용 메시지 저장
    }

    return {
        "status":   "CONFIRM",
        "message":  confirm_message,
        "context":  context,
        "ui_type":  "confirm_buttons"          # ← Streamlit 버튼 렌더링 트리거
    }

# ---------------------------------------------------------
# 외부 호출 함수
# ---------------------------------------------------------
def get_transfer_answer(question, username, context=None):
    try:
        return process_transfer(question, username, context)
    except Exception as e:
        return f"송금 처리 중 오류가 발생했습니다: {e}"


if __name__ == "__main__":
    print("Transfer Agent Ready")