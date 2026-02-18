import os
import json
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from utils.handle_sql import get_data, execute_query

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


############################################################
# 송금 정보 추출 프롬프트
############################################################

transfer_extract_template = """
You are a financial information extractor.

Extract transfer information from the user's message.

[Rules]
1. Return ONLY JSON.
2. If information is missing, return null.
3. For example, currency is KRW, USD, JPY, VND, or etc.
4. Do NOT guess.

[Output Format]
{{
  "target": string | null,
  "amount": number | null,
  "currency": string | null
}}

User Message:
{question}
"""

transfer_extract_prompt = PromptTemplate.from_template(
    transfer_extract_template
)

transfer_chain = (
    transfer_extract_prompt
    | llm
    | StrOutputParser()
)


############################################################
# JSON 파싱
############################################################

def parse_transfer_json(text: str):
    try:
        return json.loads(text)
    except:
        return {"target": None, "amount": None, "currency": None}


############################################################
# DB 검증 함수들 (DB 구조 반영)
############################################################

def get_member_id(username):
    query = f"""
    SELECT user_id
    FROM members
    WHERE username = '{username}'
    """
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
    query = f"""
    SELECT contact_name, relationship
    FROM contacts
    WHERE user_id = {user_id}
    """
    return get_data(query)


def resolve_contact_name(user_id, user_input):
    contacts = get_all_contacts(user_id)
    user_input = user_input.strip()

    for c in contacts:
        if user_input == c["contact_name"]:
            return c["contact_name"]
        if c.get("relationship") and user_input == c["relationship"]:
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
    query = f"""
    SELECT password FROM members WHERE username = '{username}'
    """
    result = get_data(query)
    return result[0]["password"] if result else None


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
    query = f"""
    UPDATE accounts
    SET balance = {new_balance}
    WHERE account_id = {account_id}
    """
    execute_query(query)


def insert_ledger(
    account_id,
    contact_id,
    amount_krw,
    balance_after,
    exchange_rate,
    target_amount,
    target_currency
):
    query = f"""
    INSERT INTO ledger (
        account_id,
        contact_id,
        transaction_type,
        amount,
        balance_after,
        exchange_rate,
        target_amount,
        target_currency_code,
        description,
        category
    )
    VALUES (
        {account_id},
        {contact_id},
        'TRANSFER',
        {-amount_krw},
        {balance_after},
        {exchange_rate},
        {target_amount},
        '{target_currency}',
        '송금',
        '이체'
    )
    """
    execute_query(query)


############################################################
# 메인 송금 로직
############################################################

def process_transfer(question: str, username: str, context: dict | None = None):

    context = context or {}

    user_id = get_member_id(username)
    if not user_id:
        return {"status": "ERROR", "message": "사용자를 찾을 수 없습니다."}


    # --------------------------------------------------
    # 1. 비밀번호 입력 단계
    # --------------------------------------------------
    if context.get("awaiting_password"):

        stored_password = get_user_password(username)  # ✅ 수정

        if not stored_password:
            return {"status": "ERROR", "message": "사용자 정보를 찾을 수 없습니다."}

        if question != stored_password:
            context["password_attempts"] = context.get("password_attempts", 0) + 1

            if context["password_attempts"] >= 5:
                return {"status": "FAIL", "message": "비밀번호 5회 오류. 송금 실패."}

            return {
                "status": "NEED_PASSWORD",
                "message": f"비밀번호 오류. 남은 기회: {5 - context['password_attempts']}",
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

        return {"status": "SUCCESS", "message": "송금이 완료되었습니다."}

    # --------------------------------------------------
    # 2. 확인 단계
    # --------------------------------------------------
    if context.get("awaiting_confirm"):

        if question.lower() != "y":
            return {"status": "CANCEL", "message": "송금이 취소되었습니다."}

        context["awaiting_confirm"] = False
        context["awaiting_password"] = True
        context["password_attempts"] = 0

        return {
            "status": "NEED_PASSWORD",
            "message": "비밀번호를 입력해주세요.",
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
                context["amount"] = float(question.strip().replace(",", "").replace("원", ""))
            except:
                return {
                    "status": "NEED_INFO",
                    "field": "amount",
                    "message": "금액을 숫자로 입력해주세요.", # 숫자 아니거나 숫자 뒤에 다른 거 붙여서 입력 시 처리 불가
                    "context": context
                }

        elif field == "currency":
            context["currency"] = question.strip().upper() # 원, 동, 달러가 아니라 KRW 처럼 입력해야 함

        context.pop("missing_field")

    # --------------------------------------------------
    # 4. 최초 요청
    # --------------------------------------------------
    if not context.get("target") and not context.get("amount") and not context.get("currency"):
        raw_result = transfer_chain.invoke({"question": question})
        info = parse_transfer_json(raw_result)

        target = info.get("target")
        amount = info.get("amount")
        currency = info.get("currency")

        context["target"] = target
        context["amount"] = amount
        context["currency"] = currency

    else:
        target = context.get("target")
        amount = context.get("amount")
        currency = context.get("currency")

    # 대상 추론
    if not target:
        context["missing_field"] = "target"
        return {
            "status": "NEED_INFO",
            "field": "target",
            "message": "송금할 대상을 입력해주세요.",
            "context": context
        }

    resolved = resolve_contact_name(user_id, target)
    if resolved:
        context["target"] = resolved
    if not resolved:
        context["missing_field"] = "target"
        return {
            "status": "NEED_INFO",
            "field": "target",
            "message": "연락처에서 찾을 수 없습니다. 정확한 이름을 입력해주세요.",
            "context": context
        }

    if not amount:
        context["missing_field"] = "amount"
        return {
            "status": "NEED_INFO",
            "field": "amount",
            "message": "송금 금액을 입력해주세요.",
            "context": context
        }

    if not currency:
        context["missing_field"] = "currency"
        return {
            "status": "NEED_INFO",
            "field": "currency",
            "message": "통화를 입력해주세요 (KRW/USD/JPY).",
            "context": context
        }

    rate = get_exchange_rate(currency)
    if rate is None:
        return {
            "status": "ERROR",
            "message": f"{currency} 환율 정보를 찾을 수 없습니다."
        }
    
    account = get_primary_account(user_id)

    amount_krw = float(amount) * rate

    if amount_krw > float(account["balance"]):
        return {"status": "ERROR", "message": "잔액이 부족합니다."}

    context = {
        "target": resolved,
        "amount": float(amount),
        "currency": currency,
        "amount_krw": amount_krw,
        "exchange_rate": rate,
        "awaiting_confirm": True
    }

    return {
        "status": "CONFIRM",
        "message": f"{resolved}에게 {amount} {currency} ({round(amount_krw,2)}원) 송금하시겠습니까? (y/n)",
        "context": context
    }


############################################################
# 외부 호출 함수
############################################################

def get_transfer_answer(question, username, context=None):
    try:
        return process_transfer(question, username, context)
    except Exception as e:
        return f"송금 처리 중 오류가 발생했습니다: {e}"


if __name__ == "__main__":
    print("Transfer Agent Ready")
