import streamlit as st
import time
import pymysql
import os
import bcrypt
from dotenv import load_dotenv

from utils.handle_sql import get_data, execute_query
from rag_agent.main_agent import run_fintech_agent
from streamlit_mic_recorder import mic_recorder
from whisper.mic_prompt import transcribe_audio_bytes

load_dotenv()

# ==========================================
# 1. 페이지 설정 및 디자인
# ==========================================
st.set_page_config(page_title="Woori AI Assistant", page_icon="🦋", layout="centered")

def local_css():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700&display=swap');
        html, body, [class*="css"] { font-family: 'Poppins', sans-serif; }
        .stApp {
            background-color: #F8FAFC;
            background-image: radial-gradient(#E0E7FF 1px, transparent 1px);
            background-size: 20px 20px;
        }
        [data-testid="stForm"] {
            background-color: rgba(255, 255, 255, 0.95);
            padding: 3rem;
            border-radius: 24px;
            box-shadow: 0 20px 40px -10px rgba(0, 0, 0, 0.05);
            border: 1px solid #EEF2FF;
            backdrop-filter: blur(10px);
        }
        div[data-baseweb="input"] > div {
            background-color: #F1F5F9;
            border-radius: 16px;
            border: 2px solid transparent;
            padding: 5px;
        }
        div[data-baseweb="input"] > div:focus-within {
            background-color: #FFFFFF;
            border: 2px solid #6366F1;
            box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1);
        }
        div.stButton > button {
            background: linear-gradient(135deg, #6366F1 0%, #0067AC 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 0.9rem !important;
            padding: 0.5rem 1rem !important;
            width: 100%;
        }
        div.stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px -5px rgba(99, 102, 241, 0.4);
        }
        /* 보조 버튼 스타일 */
        button[kind="secondary"] {
            background: transparent !important;
            border: 1px solid #CBD5E1 !important;
            color: #64748B !important;
        }
        [data-testid="stSidebar"] { background-color: #FFFFFF; border-right: 1px solid #E2E8F0; }
        h1, h2, h3 { color: #1E293B; }
    </style>
    """, unsafe_allow_html=True)

local_css()

# ==========================================
# 2. 세션 상태 초기화
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'current_user' not in st.session_state:
    st.session_state['current_user'] = None
if 'user_name_real' not in st.session_state:
    st.session_state['user_name_real'] = None
if 'page' not in st.session_state:
    st.session_state['page'] = 'login'
# 로그인 방식 상태 (pin 또는 password)
if 'login_method' not in st.session_state:
    st.session_state['login_method'] = 'pin' 
if 'messages' not in st.session_state:
    st.session_state['messages'] = [{"role": "assistant", "content": "안녕하세요! **우리 A.I 에이전트**입니다. 🦋"}]
if 'chat_sessions' not in st.session_state:
    st.session_state['chat_sessions'] = []
if 'user_input_text' not in st.session_state:
    st.session_state['user_input_text'] = ""
    
# ==========================================
# 3. 페이지 함수
# ==========================================

def login_page():
    st.write("")
    st.write("")
    
    col1, col2, col3 = st.columns([1, 5, 1]) 
    
    with col2:
        # 로그인 방식에 따라 제목과 입력창 변경
        is_pin_mode = st.session_state['login_method'] == 'pin'
        mode_title = "PIN Code" if is_pin_mode else "Password"
        
        with st.form("login_form"):
            st.markdown("<h1 style='text-align: center; font-size: 3.5rem; margin-bottom:0;'>🦋</h1>", unsafe_allow_html=True)
            st.markdown(f"<h2 style='text-align: center; color: #1E293B;'>{mode_title} Login</h2>", unsafe_allow_html=True)
            
            username = st.text_input("아이디 (Username)", placeholder="example@woorifis.com")
            
            # 모드에 따른 비밀번호 입력창 구분
            if is_pin_mode:
                password_input = st.text_input("간편 비밀번호 (PIN 6자리)", type="password", placeholder="••••••")
            else:
                password_input = st.text_input("계정 비밀번호 (Password)", type="password", placeholder="비밀번호를 입력하세요")
            
            st.markdown("####") 
            submitted = st.form_submit_button("로그인")
            
            if submitted:
                try:
                    # 두 가지 비밀번호 모두 조회 (pin_code, password)
                    sql = "SELECT pin_code, password, korean_name FROM members WHERE username = %s"
                    user_data = get_data(sql, (username,))
                    
                    if user_data:
                        db_pin = user_data[0]['pin_code']
                        db_pw = user_data[0]['password']
                        korean_name = user_data[0]['korean_name']
                        
                        target_hash = db_pin if is_pin_mode else db_pw
                        
                        # DB값이 없을 경우(기존 데이터 등) 방어 로직
                        if not target_hash:
                             st.error("해당 로그인 방식에 대한 비밀번호가 설정되지 않았습니다.")
                        else:
                            if isinstance(target_hash, str):
                                target_hash = target_hash.encode('utf-8')
                            
                            if bcrypt.checkpw(password_input.encode('utf-8'), target_hash):
                                st.session_state['logged_in'] = True
                                st.session_state['current_user'] = username
                                st.session_state['user_name_real'] = korean_name
                                st.session_state['page'] = 'chat'
                                st.rerun()
                            else:
                                st.error("비밀번호가 일치하지 않습니다.")
                    else:
                        st.error("존재하지 않는 아이디입니다.")
                except Exception as e:
                    st.error(f"시스템 오류: {e}")

        # 로그인 방식 전환 버튼 및 회원가입 버튼
        st.write("")
        b_col1, b_col2 = st.columns(2)
        
        with b_col1:
            # 토글 버튼 로직
            toggle_label = "🔑 비밀번호로 로그인" if is_pin_mode else "🔢 PIN으로 로그인"
            if st.button(toggle_label, use_container_width=True):
                st.session_state['login_method'] = 'password' if is_pin_mode else 'pin'
                st.rerun()
                
        with b_col2:
             if st.button("✨ 회원가입", type="secondary", use_container_width=True):
                 st.session_state['page'] = 'register'
                 st.rerun()

def register_page():
    st.write("")
    
    col1, col2, col3 = st.columns([1, 5, 1])
    
    with col2:
        with st.form("register_form"):
            st.markdown("<h2 style='text-align: center;'>회원가입</h2>", unsafe_allow_html=True)
            
            new_user = st.text_input("아이디 (Username)", placeholder="unique_id")
            new_name = st.text_input("이름 (Korean Name)", placeholder="홍길동")
            
            st.markdown("---")
            st.markdown("**1. 계정 비밀번호 설정** (일반 로그인용)")
            new_pw = st.text_input("비밀번호", type="password")
            new_pw_cf = st.text_input("비밀번호 확인", type="password")
            
            st.markdown("**2. PIN 번호 설정** (간편 로그인용)")
            new_pin = st.text_input("PIN Code (숫자 6자리)", type="password", max_chars=6)
            new_pin_cf = st.text_input("PIN Code 확인", type="password", max_chars=6)
            
            new_lang = st.selectbox("선호 언어", ["ko", "en", "vi", "id"], index=0)
            
            st.markdown("####")
            submit = st.form_submit_button("가입 완료")
            
            if submit:
                # 유효성 검사
                if not all([new_user, new_name, new_pw, new_pin]):
                    st.error("모든 필수 정보를 입력해주세요.")
                elif new_pw != new_pw_cf:
                    st.error("계정 비밀번호가 일치하지 않습니다.")
                elif new_pin != new_pin_cf:
                    st.error("PIN 번호가 일치하지 않습니다.")
                elif len(new_pin) != 6 or not new_pin.isdigit():
                    st.error("PIN 번호는 6자리 숫자여야 합니다.")
                else:
                    try:
                        check_sql = "SELECT username FROM members WHERE username = %s"
                        if get_data(check_sql, (new_user,)):
                            st.error("이미 존재하는 아이디입니다.")
                        else:
                            # 비밀번호 해싱 (두 개 다 수행)
                            hashed_pw = bcrypt.hashpw(new_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                            hashed_pin = bcrypt.hashpw(new_pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                            
                            # DB Insert (password, pin_code 둘 다 저장)
                            insert_sql = """
                                INSERT INTO members (username, korean_name, password, pin_code, preferred_language)
                                VALUES (%s, %s, %s, %s, %s)
                            """
                            execute_query(insert_sql, (new_user, new_name, hashed_pw, hashed_pin, new_lang))
                            
                            st.success(f"{new_name}님 가입 완료! 로그인 해주세요.")
                            time.sleep(1.5)
                            st.session_state['page'] = 'login'
                            st.rerun()
                    except Exception as e:
                        st.error(f"오류 발생: {e}")

        st.markdown("---")
        if st.button("로그인 화면으로 돌아가기", type="secondary"):
            st.session_state['page'] = 'login'
            st.rerun()

def chat_page():
    # --- 사이드바 ---
    with st.sidebar:
        st.markdown(f"""
        <div style='background-color: #F1F5F9; padding: 15px; border-radius: 15px; margin-bottom: 20px;'>
            <h3 style='margin:0; color: #1E293B; font-size: 1.2rem;'>👋 반가워요!</h3>
            <p style='margin:0; color: #64748B; font-size: 0.9rem;'>
                <b>{st.session_state.get('user_name_real', '사용자')}</b>님
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("✨ 새 대화 시작", use_container_width=True):
            st.session_state['messages'] = [{"role": "assistant", "content": "안녕하세요! **우리 A.I 에이전트**입니다. 🦋\n금융 업무부터 일상 대화까지 무엇이든 도와드릴게요."}]
            st.rerun()

        st.markdown("<div style='margin-top: auto;'></div>", unsafe_allow_html=True)
        st.markdown("---")
        if st.button("로그아웃", use_container_width=True):
            st.session_state['logged_in'] = False
            st.session_state['current_user'] = None
            st.session_state['user_name_real'] = None
            st.session_state['page'] = 'login'
            st.rerun()

    # --- 메인 채팅 화면 ---
    st.caption("🔒 Woori AI Service | Powered by Fin-Agent")
    
    # 1. 기존 메시지 렌더링
    for message in st.session_state['messages']:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # 2. 사용자 입력 처리
    if prompt := st.chat_input("메시지를 입력해 주세요..."):
        # 사용자 메시지 저장 및 표시
        st.session_state['messages'].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # 3. [변경됨] Agent 호출 및 응답 처리
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            
            # 처리 중임을 알리는 스피너
            with st.spinner("AI가 답변을 생성하고 있습니다..."):
                try:
                    # main_agent.py의 함수 호출 (번역 -> 의도파악 -> 답변생성 -> 역번역)
                    final_response = run_fintech_agent(prompt)
                except Exception as e:
                    final_response = f"죄송합니다. 오류가 발생했습니다: {e}"

            # 4. 스트리밍 효과 (Fake Stream)
            # LangChain Agent는 결과를 한 번에 주기 때문에, 
            # UI 상 자연스럽게 보이기 위해 타자 치는 효과를 냅니다.
            streamed_text = ""
            for char in final_response:
                streamed_text += char
                time.sleep(0.01) # 속도 조절
                message_placeholder.markdown(streamed_text + "▌")
            
            message_placeholder.markdown(streamed_text)
            
            # 완성된 응답을 세션에 저장
            st.session_state['messages'].append({"role": "assistant", "content": streamed_text})
            
# ==========================================
# 4. 실행 로직
# ==========================================

if st.session_state['logged_in']:
    chat_page()
else:
    if st.session_state['page'] == 'login':
        login_page()
    elif st.session_state['page'] == 'register':
        register_page()