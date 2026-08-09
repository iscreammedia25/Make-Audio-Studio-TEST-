import requests
import io
import wave
import json

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

def get_subscription_info(api_key):
    """ElevenLabs 구독 정보(보이스 슬롯 사용량 포함)를 가져옵니다."""
    api_key = api_key.strip()
    url = "https://api.elevenlabs.io/v1/user/subscription"
    headers = {"xi-api-key": api_key}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        return {
            "success": True,
            "tier": data.get("tier", "unknown"),
            "voice_limit": data.get("voice_limit", 0),
            "professional_voice_limit": data.get("professional_voice_limit", 0),
            "character_count": data.get("character_count", 0),
            "character_limit": data.get("character_limit", 0),
        }
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
        return {v['name']: {'id': v['voice_id'], 'preview': v.get('preview_url')} for v in voices if v.get('name') and v.get('voice_id')}
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code
        if status_code == 401:
            return {"error": "API Key가 유효하지 않거나 권한이 부족합니다."}
        elif status_code == 402:
            return {"error": "결제 단계 오류(402): 무료 요금제에서는 라이브러리 보이스를 API로 사용할 수 없습니다. 기본 보이스(My Voices에 등록된 보이스)를 사용해 주세요."}
        return {"error": f"HTTP 오류 발생: {status_code} - {e.response.text}"}
    except Exception as e:
        return {"error": f"예상치 못한 오류: {str(e)}"}

def _clean_tts_text(text):
    """TTS 전달 전 텍스트 정제: 따옴표 제거, 불필요한 공백 정리."""
    import re
    # 바깥쪽 따옴표 제거 ("..." 또는 '...')
    t = text.strip()
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        t = t[1:-1].strip()
    # 유니코드 따옴표 제거
    t = t.replace('“', '').replace('”', '').replace('‘', '').replace('’', '')
    # 연속 공백 정리
    t = re.sub(r'\s+', ' ', t).strip()
    return t if t else text

def generate_audio(api_key, text, voice_id, stability=0.5, similarity_boost=0.75, style=0.0, use_speaker_boost=True):
    """ElevenLabs API를 사용하여 텍스트로부터 음성(WAV)을 생성합니다."""
    api_key = api_key.strip()
    text = _clean_tts_text(text)
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

def normalize_audio(audio_bytes, target_dBFS=-20.0):
    """ffmpeg loudnorm 필터를 사용하여 오디오 볼륨을 정규화합니다."""
    import subprocess
    import imageio_ffmpeg
    import tempfile
    import os

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_in:
        tmp_in.write(audio_bytes)
        tmp_in_path = tmp_in.name
    tmp_out_path = tmp_in_path.replace(".mp3", "_norm.mp3")
    try:
        subprocess.run(
            [ffmpeg_exe, "-y", "-i", tmp_in_path, "-filter:a", "loudnorm", "-vn", tmp_out_path],
            check=True, capture_output=True
        )
        with open(tmp_out_path, "rb") as f:
            return f.read()
    except Exception:
        return audio_bytes
    finally:
        if os.path.exists(tmp_in_path): os.unlink(tmp_in_path)
        if os.path.exists(tmp_out_path): os.unlink(tmp_out_path)

def overlay_audio(audio_bytes_list):
    """여러 MP3를 동시에 재생(amix 오버레이)합니다."""
    import subprocess, imageio_ffmpeg, tempfile, os

    if len(audio_bytes_list) == 1:
        return audio_bytes_list[0]

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    tmp_files = []
    tmp_out = None
    try:
        for audio_bytes in audio_bytes_list:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(audio_bytes)
                tmp_files.append(f.name)

        n = len(tmp_files)
        inputs = []
        for path in tmp_files:
            inputs.extend(["-i", path])

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            tmp_out = f.name

        subprocess.run(
            [ffmpeg_exe, "-y"] + inputs + [
                "-filter_complex", f"amix=inputs={n}:duration=longest:normalize=0",
                "-vn", "-b:a", "192k", tmp_out
            ],
            check=True, capture_output=True
        )
        with open(tmp_out, "rb") as f:
            return f.read()
    except Exception as e:
        print(f"overlay_audio error: {e}")
        return audio_bytes_list[0]
    finally:
        for f in tmp_files:
            if os.path.exists(f): os.unlink(f)
        if tmp_out and os.path.exists(tmp_out): os.unlink(tmp_out)


def merge_audio(audio_data_list, silence_between_ms=80):
    """ffmpeg concat demuxer로 여러 MP3를 병합합니다."""
    import subprocess
    import imageio_ffmpeg
    import tempfile
    import os

    if len(audio_data_list) == 1:
        return audio_data_list[0]

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    tmp_files = []
    list_path = None
    tmp_out = None
    try:
        for audio_bytes in audio_data_list:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(audio_bytes)
                tmp_files.append(f.name)
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt") as lf:
            list_path = lf.name
            for path in tmp_files:
                lf.write(f"file '{path}'\n")
        tmp_out = list_path.replace(".txt", "_merged.mp3")
        subprocess.run(
            [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-vn", "-b:a", "192k", tmp_out],
            check=True, capture_output=True
        )
        with open(tmp_out, "rb") as f:
            return f.read()
    except Exception as e:
        print(f"merge_audio error: {e}")
        return b"".join(audio_data_list)
    finally:
        for f in tmp_files:
            if os.path.exists(f): os.unlink(f)
        if list_path and os.path.exists(list_path): os.unlink(list_path)
        if tmp_out and os.path.exists(tmp_out): os.unlink(tmp_out)

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

def generate_voice_design_preview(api_key, gender, age, accent, text="The quick brown fox jumps over the lazy dog. This is a longer sample text to meet the minimum requirement of one hundred characters for the ElevenLabs Voice Design API preview generation.", custom_description=None):
    """일레븐랩스 보이스 디자인 API를 사용하여 임시 보이스 샘플을 생성합니다."""
    api_key = api_key.strip()
    url = "https://api.elevenlabs.io/v1/text-to-voice/design"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }

    if custom_description and len(custom_description.strip()) >= 20:
        description = custom_description.strip()
    else:
        description = f"A {gender} voice, {age}, with a {accent} accent, speaking clearly for a children's storybook."

    data = {
        "voice_description": description,
        "text": text,
        "auto_generate_text": False
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        
        res_json = response.json()
        previews = res_json.get("previews", [])
        
        if not previews:
            return {"success": False, "error": "생성된 보이스 샘플이 없습니다."}

        import base64
        samples = [
            {
                "audio_bytes": base64.b64decode(p["audio_base_64"]),
                "generated_voice_id": p["generated_voice_id"],
            }
            for p in previews
        ]
        return {"success": True, "samples": samples}
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            error_msg += f" - {e.response.text}"
        return {"success": False, "error": error_msg}

def create_voice_from_design(api_key, voice_name, generated_voice_id, description="Created via Voice Design"):
    """디자인된 임시 보이스를 내 계정에 영구 저장합니다."""
    api_key = api_key.strip()
    url = "https://api.elevenlabs.io/v1/text-to-voice"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }
    data = {
        "voice_name": voice_name,
        "voice_description": description,
        "generated_voice_id": generated_voice_id
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return {"success": True, "voice_id": response.json().get("voice_id")}
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            error_msg += f" - {e.response.text}"
        return {"success": False, "error": error_msg}

def concat_audio(audio_bytes_list):
    """여러 MP3 바이트를 순서대로 연결합니다 (mBook 전체 병합용)."""
    import subprocess
    import imageio_ffmpeg
    import tempfile
    import os

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    tmp_files = []
    list_path = None
    tmp_out = None
    try:
        for audio_bytes in audio_bytes_list:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(audio_bytes)
                tmp_files.append(f.name)
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".txt") as lf:
            list_path = lf.name
            for path in tmp_files:
                lf.write(f"file '{path}'\n")
        tmp_out = list_path.replace(".txt", "_concat.mp3")
        subprocess.run(
            [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-vn", "-b:a", "192k", tmp_out],
            check=True, capture_output=True
        )
        with open(tmp_out, "rb") as f:
            return f.read()
    except Exception as e:
        print(f"concat_audio error: {e}")
        return b"".join(audio_bytes_list)
    finally:
        for f in tmp_files:
            if os.path.exists(f): os.unlink(f)
        if list_path and os.path.exists(list_path): os.unlink(list_path)
        if tmp_out and os.path.exists(tmp_out): os.unlink(tmp_out)

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
