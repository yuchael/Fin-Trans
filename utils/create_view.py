from utils.handle_sql import get_data, execute_query


def get_user_id(username: str) -> int:
    query = f"""
        SELECT user_id
        FROM members
        WHERE username = '{username}'
    """
    result = get_data(query)

    if not result:
        raise ValueError("사용자를 찾을 수 없습니다.")

    return result[0]["user_id"]


def create_user_views(username: str):
    """
    로그인한 사용자의 전용 View들 생성
    """
    user_id = get_user_id(username)

    # 1️⃣ 사용자 기본 정보
    profile_view_sql = f"""
        CREATE OR REPLACE VIEW current_user_profile AS
        SELECT user_id, username, korean_name
        FROM members
        WHERE user_id = {user_id}
    """

    # 2️⃣ 사용자 계좌 정보
    accounts_view_sql = f"""
        CREATE OR REPLACE VIEW current_user_accounts AS
        SELECT account_id, balance, currency_code, is_primary
        FROM accounts
        WHERE user_id = {user_id}
    """

    # 3️⃣ 사용자 거래 내역
    transactions_view_sql = f"""
        CREATE OR REPLACE VIEW current_user_transactions AS
        SELECT t.transaction_id,
               t.account_id,
               t.transaction_type,
               t.amount,
               t.balance_after,
               t.description,
               t.category,
               t.created_at
        FROM ledger t
        JOIN accounts a ON t.account_id = a.account_id
        WHERE a.user_id = {user_id}
    """

    execute_query(profile_view_sql)
    execute_query(accounts_view_sql)
    execute_query(transactions_view_sql)

    return [
        "current_user_profile",
        "current_user_accounts",
        "current_user_transactions"
    ]
