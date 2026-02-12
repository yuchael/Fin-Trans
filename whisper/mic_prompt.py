import os
import speech_recognition as sr
from openai import OpenAI
from dotenv import load_dotenv  # 추가된 부분
import io

# 1. .env 파일 로드
# 이 함수가 실행되면 .env 파일의 내용이 환경 변수로 등록됩니다.
load_dotenv()

# 2. 환경 변수에서 API 키 가져오기
api_key = os.getenv("OPENAI_API_KEY")

# 키가 제대로 로드되었는지 확인 (디버깅용)
if not api_key:
    raise ValueError("❌ .env 파일에서 OPENAI_API_KEY를 찾을 수 없습니다.")

# OpenAI 클라이언트 설정
client = OpenAI(api_key=api_key)

def listen_from_mic():
    """
    마이크로부터 음성을 듣고 임시 wav 파일로 저장하는 함수
    """
    r = sr.Recognizer()
    
    with sr.Microphone() as source:
        print("🎤 말씀해 주세요 (듣고 있습니다...)")
        
        # 배경 소음 수준을 조정하여 정확도 향상
        r.adjust_for_ambient_noise(source)
        
        try:
            # 음성 감지 및 녹음 (타임아웃 설정 추가: 5초 동안 말 없으면 종료)
            audio = r.listen(source, timeout=5, phrase_time_limit=10)
            print("✅ 녹음 완료! 변환 중...")
            
            # Whisper API는 파일 형태를 요구하므로 임시 파일로 저장
            filename = "my_voice.wav"
            with open(filename, "wb") as f:
                f.write(audio.get_wav_data())
                
            return filename
        except sr.WaitTimeoutError:
            print("⏳ 음성이 감지되지 않았습니다.")
            return None

def transcribe_audio(filename):
    """
    저장된 오디오 파일을 OpenAI Whisper API로 텍스트로 변환하는 함수
    """
    if not filename: return None
    
    try:
        with open(filename, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file
                # language="ko" # 필요 시 언어 강제 설정 가능
            )
        return transcript.text
    except Exception as e:
        print(f"오류 발생 (STT): {e}")
        return None

def transcribe_audio_bytes(audio_bytes):
    """
    브라우저에서 넘어온 오디오 바이트 데이터를 Whisper로 변환
    """
    if not audio_bytes: 
        return None
    
    try:
        # OpenAI API는 파일 객체 형태(name 속성 필요)를 원하므로 BytesIO 래핑
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "voice.wav"  # 가상의 파일명 지정 (필수)

        transcript = client.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file,
            #language="ko" # 한국어 보정
        )
        return transcript.text
    except Exception as e:
        print(f"STT Error: {e}")
        return None

def ask_llm(text):
    """
    변환된 텍스트를 LLM(GPT)에게 보내고 답변을 받는 함수
    """
    try:
        with open("prompt/mic_system_prompt.md", "r", encoding="utf-8") as f:
                system_prompt_content = f.read()
            

        # 2. API 호출에 적용
        response = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[
                {
                    "role": "system", 
                    "content": system_prompt_content
                },
                {
                    "role": "user", 
                    "content": text
                }
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"오류 발생 (LLM): {e}")
        return None



# --- 메인 실행 흐름 ---
if __name__ == "__main__":
    retry_mic = False  # 음성 인식 자동 재시도를 제어할 상태 변수 추가

    while True:
        # 1. 입력 방식 선택
        if retry_mic:
            # LLM이 모른다고 답변해서 질문 단계 없이 자동으로 음성 인식 시작
            choice = 'm'
            retry_mic = False  # 다음 루프를 위해 플래그 초기화
            print("\n🔄 LLM이 답변을 찾지 못했습니다. 자동으로 음성 인식을 다시 시작합니다.")
        else:
            # 일반적인 경우: 사용자에게 입력 방식 선택 요청
            choice = input("\n⌨️ 텍스트 입력은 't', 🎤 음성 입력은 'm', 종료하려면 'q'를 눌러주세요: ").strip().lower()

        if choice == 'q' or choice == '종료':
            print("👋 대화를 종료합니다.")
            break

        # [A] 텍스트 입력 방식
        if choice == 't':
            user_prompt = input("💬 질문을 타이핑해 주세요: ").strip()
            
            if not user_prompt:
                print("⚠️ 아무것도 입력되지 않았습니다. 다시 시도해 주세요.")
                continue
                
            if "종료" in user_prompt or "그만" in user_prompt:
                print("👋 대화를 종료합니다.")
                break

        # [B] 마이크 음성 입력 방식
        elif choice == 'm':
            audio_file = listen_from_mic()
            
            # 음성 감지 실패 시
            if not audio_file:
                print("⚠️ 다시 시도합니다. 마이크에 가까이 대고 말씀해 주세요.")
                continue 
            
            # 음성을 텍스트로 변환 (Whisper)
            user_prompt = transcribe_audio(audio_file)
            
            # 파일은 변환 후 바로 삭제
            if os.path.exists(audio_file):
                os.remove(audio_file)
            
            # 텍스트 변환 실패 시
            if not user_prompt or user_prompt.strip() == "":
                print("⚠️ 음성 인식에 실패했거나 아무 말씀도 하지 않으셨습니다. 다시 질문해 주세요.")
                continue

            print(f"\n🗣️ 인식된 질문: {user_prompt}")
            
            if "종료" in user_prompt or "그만" in user_prompt:
                print("👋 대화를 종료합니다.")
                break

        # [C] 잘못된 키 입력 처리
        else:
            print("⚠️ 잘못된 입력입니다. 't', 'm', 'q' 중에서 하나를 입력해 주세요.")
            continue

        print("-" * 30)
        
        # 2. LLM에게 질문하고 답변 받기 (GPT)
        ai_response = ask_llm(user_prompt)
        
        # 3. LLM 답변 출력 및 재시도 조건 확인
        if ai_response:
            print(f"🤖 AI 답변:\n{ai_response}")
            
            # --- 추가된 로직: LLM이 모른다고 했을 때 재시도 처리 ---
            # LLM의 답변에 포함될 수 있는 '모른다'는 뉘앙스의 키워드들 리스트
            unknown_keywords = ["모르겠", "알 수 없", "이해하지 못", "죄송하지만"]
            
            # 답변 문자열 안에 위 키워드가 하나라도 포함되어 있는지 검사
            if any(keyword in ai_response for keyword in unknown_keywords):
                retry_mic = True  # 다음 반복에서 자동으로 마이크가 켜지도록 설정
                
        else:
            print("⚠️ AI가 답변을 생성하지 못했습니다. 다시 시도해 주세요.")