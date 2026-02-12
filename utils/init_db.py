import pymysql
import os
import bcrypt
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

def get_connection():
    return pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        db=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT', 3306)),
        charset='utf8mb4'
    )

def init_database():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            print("🔧 데이터베이스 초기화 시작...")

            # 1. 외래키 체크 해제 (삭제/생성 시 오류 방지)
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

            # 2. 기존 테이블 삭제
            print("🗑️ 기존 members 테이블 삭제 중...")
            cursor.execute("DROP TABLE IF EXISTS members")

            # 3. 테이블 새로 생성 
            # [수정됨] id -> user_id 로 변경 (accounts 테이블과의 관계 유지를 위해 필수)
            print("✨ members 테이블 생성 중...")
            create_sql = """
            CREATE TABLE members (
                user_id INT AUTO_INCREMENT PRIMARY KEY, 
                username VARCHAR(50) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                pin_code VARCHAR(255) NOT NULL,
                korean_name VARCHAR(50) NOT NULL,
                preferred_language VARCHAR(10) DEFAULT 'ko',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            cursor.execute(create_sql)
            
            # 4. 외래키 체크 다시 활성화
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

            # 5. 더미 데이터 준비
            dummy_users = [
                {
                    "username": "user_kr",
                    "korean_name": "김철수",
                    "pw": "1234",
                    "pin": "123456",
                    "lang": "ko"
                },
                {
                    "username": "user_us",
                    "korean_name": "John Miller",
                    "pw": "1234",
                    "pin": "123456",
                    "lang": "en"
                },
                {
                    "username": "user_vn",
                    "korean_name": "Nguyen Minh",
                    "pw": "1234",
                    "pin": "123456",
                    "lang": "vi"
                }
            ]

            print("🚀 더미 데이터 적재 중 (암호화 적용)...")
            
            insert_sql = """
            INSERT INTO members (username, korean_name, password, pin_code, preferred_language)
            VALUES (%s, %s, %s, %s, %s)
            """

            for u in dummy_users:
                hashed_pw = bcrypt.hashpw(u['pw'].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                hashed_pin = bcrypt.hashpw(u['pin'].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                
                cursor.execute(insert_sql, (
                    u['username'], 
                    u['korean_name'], 
                    hashed_pw, 
                    hashed_pin, 
                    u['lang']
                ))

            conn.commit()
            print("✅ DB 초기화 및 더미 데이터 생성 완료!")
            print("-------------------------------------------------")
            print("👉 테스트 계정 정보 (모든 계정 동일)")
            print("   비밀번호(Password): 1234")
            print("   PIN번호(Pin Code): 123456")

    except Exception as e:
        conn.rollback()
        print(f"❌ 오류 발생: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_database()