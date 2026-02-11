import os
import speech_recognition as sr
from openai import OpenAI
from dotenv import load_dotenv  # 추가된 부분

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
                file=audio_file,
                # language="ko" # 필요 시 언어 강제 설정 가능
            )
        return transcript.text
    except Exception as e:
        print(f"오류 발생 (STT): {e}")
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
    # 1. 마이크 입력 받기
    audio_file = listen_from_mic()
    
    if audio_file:
        # 2. 음성을 텍스트로 변환 (Whisper)
        user_prompt = transcribe_audio(audio_file)
        
        if user_prompt:
            print(f"\n🗣️ 인식된 질문: {user_prompt}\n")
            print("-" * 30)
            
            # 3. LLM에게 질문하고 답변 받기 (GPT)
            ai_response = ask_llm(user_prompt)
            
            if ai_response:
                print(f"🤖 AI 답변:\n{ai_response}")
            
            # 임시 파일 삭제
            if os.path.exists(audio_file):
                os.remove(audio_file)
        else:
            print("음성 인식에 실패했습니다.")