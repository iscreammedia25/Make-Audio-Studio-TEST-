import requests
import io
import wave

def check_api_key(api_key):
    """API 키의 유효성을 테스트합니다. /v1/models는 일반적으로 더 넓은 권한을 가집니다."""
    api_key = api_key.strip()
    # v1/models는 대개의 키가 읽기 권한을 가집니다.
    url = "https://api.elevenlabs.io/v1/models"
    headers = {"xi-api-key": api_key}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return {"success": True, "details": "연결 성공 (Models access OK)"}
        elif response.status_code == 401:
            return {"success": False, "error": f"인증 실패: API Key가 잘못되었거나 권한이 부족합니다. ({response.text})"}
        else:
            return {"success": False, "error": f"Status {response.status_code}: {response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def get_voices(api_key):
    """ElevenLabs에서 사용 가능한 목소리 목록을 가져옵니다."""
    api_key = api_key.strip()
    url = "https://api.elevenlabs.io/v1/voices"
    headers = {"xi-api-key": api_key}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        voices = response.json().get('voices', [])
        return {v['name']: {'id': v['voice_id'], 'preview': v.get('preview_url')} for v in voices}
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        if status_code == 401:
            return {"error": "API Key가 유효하지 않거나 권한이 부족합니다."}
        elif status_code == 402:
            return {"error": "결제 단계 오류(402): 무료 요금제에서는 라이브러리 보이스를 API로 사용할 수 없습니다. 기본 보이스(My Voices에 등록된 보이스)를 사용해 주세요."}
        return {"error": f"HTTP 오류 발생: {status_code} - {e.response.text}"}
    except Exception as e:
        return {"error": f"예상치 못한 오류: {str(e)}"}

def generate_audio(api_key, text, voice_id, stability=0.5, similarity_boost=0.75, style=0.0, use_speaker_boost=True):
    """ElevenLabs API를 사용하여 텍스트로부터 음성(WAV)을 생성합니다."""
    api_key = api_key.strip()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "Accept": "audio/mpeg", 
        "Content-Type": "application/json",
        "xi-api-key": api_key
    }
    
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": use_speaker_boost
        }
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.content
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        if status_code == 402:
            return {"error": "요금제 제한(402): 무료 요금제는 보이스 라이브러리의 목소리를 API로 호출할 수 없습니다. ElevenLabs 사이트의 'My Voices'에 있는 기본 보이스를 선택하거나 요금제를 업그레이드하세요."}
        return {"error": f"HTTP 오류 발생: {status_code} - {e.response.text}"}
    except Exception as e:
        return {"error": f"예상치 못한 오류: {str(e)}"}

def add_voice(api_key, name, audio_bytes):
    """ElevenLabs에 새로운 목소리를 추가(클로닝)합니다."""
    api_key = api_key.strip()
    url = "https://api.elevenlabs.io/v1/voices/add"
    headers = {"xi-api-key": api_key}
    
    # multipart/form-data 전송을 위해 files 파라미터 사용
    data = {
        "name": name,
        "description": f"Cloned via Make Audio Studio on {name}"
    }
    
    files = [
        ("files", (f"{name}.mp3", audio_bytes, "audio/mpeg"))
    ]
    
    try:
        response = requests.post(url, headers=headers, data=data, files=files)
        response.raise_for_status()
        return {"success": True, "voice_id": response.json().get("voice_id")}
    except requests.exceptions.HTTPError as e:
        return {"success": False, "error": f"HTTP 오류: {e.response.status_code} - {e.response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def merge_audio(audio_data_list):
    """여러 MP3 바이트 데이터를 하나로 병합합니다. (단순 바이너리 결합)"""
    # MP3는 프레임 단위로 구성되어 있어 단순 결합해도 대부분의 플레이어에서 연속 재생됨.
    combined = b"".join(audio_data_list)
    return combined

def isolate_audio(api_key, audio_bytes):
    """ElevenLabs Audio Isolation API를 사용하여 배경음악 및 노이즈를 제거합니다."""
    api_key = api_key.strip()
    url = "https://api.elevenlabs.io/v1/audio-isolation"
    headers = {"xi-api-key": api_key}
    
    files = [
        ("audio", ("input.mp3", audio_bytes, "audio/mpeg"))
    ]
    
    try:
        response = requests.post(url, headers=headers, files=files)
        response.raise_for_status()
        return {"success": True, "audio_bytes": response.content}
    except requests.exceptions.HTTPError as e:
        return {"success": False, "error": f"HTTP 오류: {e.response.status_code} - {e.response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def apply_speed_control(audio_bytes, speed):
    """ffmpeg의 atempo 필터를 사용하여 피치를 유지하며 오디오 속도를 조절합니다."""
    if speed == 1.0:
        return audio_bytes
        
    import subprocess
    import imageio_ffmpeg
    import tempfile
    import os

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_in:
        tmp_in.write(audio_bytes)
        tmp_in_path = tmp_in.name
        
    tmp_out_path = tmp_in_path.replace(".mp3", "_speed.mp3")
    
    # ffmpeg 커맨드: atempo 필터를 사용해 피치 유지
    # 0.5 ~ 2.0 사이의 값 지원 (우리의 슬라이더는 0.7 ~ 1.5)
    cmd = [
        ffmpeg_exe, "-y", "-i", tmp_in_path,
        "-filter:a", f"atempo={speed}",
        "-vn", tmp_out_path
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        with open(tmp_out_path, "rb") as f:
            processed_audio = f.read()
        return processed_audio
    except Exception as e:
        print(f"Speed control error: {e}")
        return audio_bytes # 실패 시 원본 반환
    finally:
        if os.path.exists(tmp_in_path): os.unlink(tmp_in_path)
        if os.path.exists(tmp_out_path): os.unlink(tmp_out_path)
