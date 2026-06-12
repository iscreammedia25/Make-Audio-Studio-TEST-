import sys
if sys.version_info < (3, 10):
    print(f"\n⚠️  Python {sys.version_info.major}.{sys.version_info.minor} 감지됨.")
    print("이 앱은 Python 3.10 이상을 권장합니다.")
    print("Homebrew로 설치: brew install python@3.11")
    print("설치 후 가상환경 재생성: python3.11 -m venv venv && source venv/bin/activate\n")

import streamlit as st
import processor
import audio_engine
import exporter
import json
from ui_helpers import voice_selector_ui
import llm_helper
import moviepy as mp
import tempfile
import os
import io
import traceback
import concurrent.futures
from dotenv import load_dotenv, set_key, find_dotenv
import time
import uuid
import shutil

_DOTENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
_SESSIONS_ROOT = os.path.join(os.path.dirname(__file__), ".sessions")
_SESSION_BACKUP_MAX_AGE = 48 * 3600   # 48시간
_SESSION_CLEANUP_AGE   = 7 * 86400    # 7일 지난 세션 폴더 자동 삭제
_PERSISTENT_KEYS = [
    "parsed_data_dict", "voice_mappings_dict", "script_parsed_dict",
    "characters", "character_voice_mappings", "character_confirmed",
    "speed_settings",
]

def _save_key_to_env(var_name: str, value: str):
    if not os.path.exists(_DOTENV_PATH):
        open(_DOTENV_PATH, "a").close()
    set_key(_DOTENV_PATH, var_name, value)

def _session_token() -> str:
    """URL query param ?t= 에서 토큰을 읽거나 없으면 새로 생성."""
    token = st.query_params.get("t")
    if not token:
        token = uuid.uuid4().hex[:12]
        st.query_params["t"] = token
    return token

def _session_dir() -> str:
    return os.path.join(_SESSIONS_ROOT, _session_token())

def _backup_path() -> str:
    return os.path.join(_session_dir(), "backup.json")

def _audio_dir() -> str:
    return os.path.join(_session_dir(), "audio")

def _cleanup_old_sessions():
    """7일 이상 된 세션 폴더를 조용히 삭제."""
    if not os.path.isdir(_SESSIONS_ROOT):
        return
    cutoff = time.time() - _SESSION_CLEANUP_AGE
    for name in os.listdir(_SESSIONS_ROOT):
        folder = os.path.join(_SESSIONS_ROOT, name)
        backup = os.path.join(folder, "backup.json")
        try:
            mtime = os.path.getmtime(backup) if os.path.exists(backup) else os.path.getmtime(folder)
            if mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass

def _autosave():
    """중요 세션 상태와 오디오 캐시를 사용자별 폴더에 저장."""
    if not any(st.session_state.get("script_parsed_dict", {}).values()):
        return
    last_save = st.session_state.get("_last_autosave", 0)
    if time.time() - last_save < 10:
        return
    sdir = _session_dir()
    os.makedirs(sdir, exist_ok=True)
    # 세션 상태 JSON 저장
    state = {k: st.session_state.get(k) for k in _PERSISTENT_KEYS}
    state["_saved_at"] = time.time()
    try:
        with open(_backup_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass
    # 오디오 캐시 저장 (이미 있는 파일은 skip)
    for diff, cache in st.session_state.get("audio_cache_dict", {}).items():
        if not cache:
            continue
        diff_dir = os.path.join(_audio_dir(), diff)
        os.makedirs(diff_dir, exist_ok=True)
        for line_key, audio_bytes in cache.items():
            if not isinstance(audio_bytes, bytes):
                continue
            safe_key = line_key.replace("/", "_").replace("\\", "_")
            fpath = os.path.join(diff_dir, f"{safe_key}.mp3")
            if not os.path.exists(fpath):
                try:
                    with open(fpath, "wb") as f:
                        f.write(audio_bytes)
                except Exception:
                    pass
    st.session_state["_last_autosave"] = time.time()

def _autorestore():
    """앱 시작 시 해당 사용자의 최근 백업이 있으면 자동 복원."""
    if any(st.session_state.get("script_parsed_dict", {}).values()):
        return
    bp = _backup_path()
    if not os.path.exists(bp):
        return
    try:
        with open(bp, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if time.time() - saved.get("_saved_at", 0) > _SESSION_BACKUP_MAX_AGE:
            return
        for k in _PERSISTENT_KEYS:
            if k in saved and saved[k] is not None:
                st.session_state[k] = saved[k]
        # 오디오 캐시 복원
        adir = _audio_dir()
        if os.path.isdir(adir):
            audio_cache = {d: {} for d in ["Normal", "Easy", "Difficult", "mBook"]}
            for diff in audio_cache:
                diff_dir = os.path.join(adir, diff)
                if not os.path.isdir(diff_dir):
                    continue
                for fname in os.listdir(diff_dir):
                    if not fname.endswith(".mp3"):
                        continue
                    try:
                        with open(os.path.join(diff_dir, fname), "rb") as f:
                            audio_cache[diff][fname[:-4]] = f.read()
                    except Exception:
                        pass
            st.session_state["audio_cache_dict"] = audio_cache
        st.session_state["_restored_from_backup"] = True
    except Exception:
        pass

load_dotenv(_DOTENV_PATH)

# 감정(Mood)별 ElevenLabs 파라미터 프리셋
MOOD_PRESETS = {
    "Neutral": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.1},
    "Happy": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.4},
    "Sad": {"stability": 0.72, "similarity_boost": 0.75, "style": 0.1},
    "Angry": {"stability": 0.38, "similarity_boost": 0.85, "style": 0.7},
    "Excited": {"stability": 0.32, "similarity_boost": 0.88, "style": 0.8},
    "Whispering": {"stability": 0.88, "similarity_boost": 0.65, "style": 0.0}
}

# 페이지 설정
st.set_page_config(page_title="동화 대본 자동 더빙 에이전트", layout="wide")

# 세션 상태 초기화 (저장된 키가 있으면 .env에서 자동 로드)
if 'api_key' not in st.session_state:
    st.session_state.api_key = os.environ.get("ELEVENLABS_API_KEY", "")
if 'gemini_api_key' not in st.session_state:
    st.session_state.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
if 'voices' not in st.session_state:
    st.session_state.voices = {}
if 'subscription_info' not in st.session_state:
    st.session_state.subscription_info = None

# 난이도별 데이터 관리 (Normal, Easy, Difficult, mBook)
DIFFICULTIES = ["Normal", "Easy", "Difficult", "mBook"]
if 'parsed_data_dict' not in st.session_state:
    st.session_state.parsed_data_dict = {d: [] for d in DIFFICULTIES}
if 'voice_mappings_dict' not in st.session_state:
    st.session_state.voice_mappings_dict = {d: {} for d in DIFFICULTIES}
if 'audio_cache_dict' not in st.session_state:
    st.session_state.audio_cache_dict = {d: {} for d in DIFFICULTIES}
if 'merged_scene_cache' not in st.session_state:
    st.session_state.merged_scene_cache = {d: {} for d in DIFFICULTIES}
if 'merged_scene_cache_size' not in st.session_state:
    st.session_state.merged_scene_cache_size = {d: 0 for d in DIFFICULTIES}
if 'generation_errors' not in st.session_state:
    st.session_state.generation_errors = []
if 'seg_page' not in st.session_state:
    st.session_state.seg_page = {d: 0 for d in DIFFICULTIES}
if 'speed_settings' not in st.session_state:
    st.session_state.speed_settings = {"내레이션": 1.0}

if 'characters' not in st.session_state:
    st.session_state.characters = {}
if 'character_voice_mappings' not in st.session_state:
    st.session_state.character_voice_mappings = {}
if 'character_confirmed' not in st.session_state:
    st.session_state.character_confirmed = False
if 'cloned_voice_id' not in st.session_state:
    st.session_state.cloned_voice_id = None
if 'cloned_voice_bytes' not in st.session_state:
    st.session_state.cloned_voice_bytes = None
if 'last_uploaded_files' not in st.session_state:
    st.session_state.last_uploaded_files = []
if 'script_parsed_dict' not in st.session_state:
    st.session_state.script_parsed_dict = {d: False for d in DIFFICULTIES}

# 전체 리셋 함수
def reset_all_state():
    st.session_state.script_parsed_dict = {d: False for d in DIFFICULTIES}
    st.session_state.parsed_data_dict = {d: [] for d in DIFFICULTIES}
    st.session_state.audio_cache_dict = {d: {} for d in DIFFICULTIES}
    st.session_state.merged_scene_cache = {d: {} for d in DIFFICULTIES}
    st.session_state.merged_scene_cache_size = {d: 0 for d in DIFFICULTIES}
    st.session_state.voice_mappings_dict = {d: {} for d in DIFFICULTIES}
    st.session_state.characters = {}
    st.session_state.character_voice_mappings = {}
    st.session_state.character_confirmed = False
    st.session_state.design_previews = {}
    st.session_state.clone_previews = {}
    # 이 사용자의 세션 폴더 전체 삭제 → 다음 시작 시 복원 안 됨
    try:
        shutil.rmtree(_session_dir(), ignore_errors=True)
    except Exception:
        pass

if 'design_previews' not in st.session_state:
    st.session_state.design_previews = {}
if 'clone_previews' not in st.session_state:
    st.session_state.clone_previews = {}

# 세션이 새로 시작됐을 때 자동 복원 + 오래된 세션 정리
if '_session_initialized' not in st.session_state:
    _cleanup_old_sessions()
    _autorestore()
    st.session_state['_session_initialized'] = True


@st.fragment
def audio_player_display(current_view_diff: str, difficulty_suffix: str):
    """오디오 플레이어 + 다운로드 섹션. 부분 렌더링으로 전체 페이지 재렌더 방지."""
    if not st.session_state.audio_cache_dict[current_view_diff]:
        return

    current_scene = None
    lines_mapping = {}
    for item in st.session_state.parsed_data_dict[current_view_diff]:
        key = f"{item['scene']}_{item['line']}"
        if key not in lines_mapping:
            lines_mapping[key] = []
        lines_mapping[key].append(item)

    for line_key, segs in lines_mapping.items():
        scene_tag = segs[0]['scene']
        if scene_tag != current_scene:
            current_scene = scene_tag
            st.subheader(f"🎬 Scene: {current_scene}")

        if line_key in st.session_state.audio_cache_dict[current_view_diff]:
            with st.container(border=True):
                cols = st.columns([1.5, 5.5, 2, 1.5, 1.5])
                cols[0].write(f"**ID: {segs[0]['line']}**")

                content_html = ""
                for seg in segs:
                    is_dialogue = seg['type'] == '대사'
                    text_val = seg['text']
                    if is_dialogue and not (text_val.startswith(('"', "'")) and text_val.endswith(('"', "'"))):
                        text_val = f'"{text_val}"'
                    color = "blue" if is_dialogue else "gray"
                    content_html += f'<span style="color:{color};">[{seg["character"]}]</span> {text_val} '
                cols[1].markdown(content_html, unsafe_allow_html=True)

                cols[2].audio(st.session_state.audio_cache_dict[current_view_diff][line_key], format="audio/mp3")

                _bid = segs[0].get('book_id', 'Unknown')
                _seq = segs[0].get('seq_num', 'ST00')
                if current_view_diff == "mBook":
                    dl_filename = f"{_bid}_mBook_{_seq}_A.mp3"
                else:
                    dl_filename = f"{_bid}_{segs[0].get('scene_num','SC00')}_{_seq}_{difficulty_suffix}.mp3"
                cols[3].download_button("⬇️ 다운", data=st.session_state.audio_cache_dict[current_view_diff][line_key], file_name=dl_filename, mime="audio/mpeg", key=f"dl_{line_key}", use_container_width=True)

                if cols[4].button("🔄 다시 생성", key=f"regen_{line_key}"):
                    with st.spinner(f"ID: {segs[0]['line']} 문장 다시 생성 중..."):
                        try:
                            regen_audios = []
                            for seg in segs:
                                char_name = seg['character']
                                voice_id = st.session_state.voice_mappings_dict[current_view_diff].get(seg['segment_id'])
                                if not voice_id:
                                    if char_name == '내레이션':
                                        voice_id = st.session_state.get('all_narration_voice_id', '')
                                    else:
                                        voice_id = st.session_state.character_voice_mappings.get(char_name, '')
                                if voice_id:
                                    audio_bytes = audio_engine.generate_audio(st.session_state.api_key, seg['text'], voice_id)
                                    if isinstance(audio_bytes, bytes):
                                        current_speed = st.session_state.speed_settings.get(char_name, 1.0)
                                        if current_speed != 1.0:
                                            audio_bytes = audio_engine.apply_speed_control(audio_bytes, current_speed)
                                        audio_bytes = audio_engine.normalize_audio(audio_bytes)
                                        regen_audios.append(audio_bytes)
                            if regen_audios:
                                st.session_state.audio_cache_dict[current_view_diff][line_key] = audio_engine.merge_audio(regen_audios)
                                st.session_state.merged_scene_cache[current_view_diff] = {}
                                st.session_state.merged_scene_cache_size[current_view_diff] = 0
                                st.success(f"ID: {segs[0]['line']} 재생성 완료!")
                                st.rerun(scope="fragment")
                            else:
                                st.error("보이스 설정이 되어 있지 않습니다.")
                        except Exception as e:
                            st.error(f"재생성 중 오류 발생: {str(e)}")

    # 다운로드 섹션
    st.divider()
    st.header("4. 결과물 전체 다운로드")
    col1, col2 = st.columns(2)
    with col1:
        zip_data = exporter.create_individual_zip(difficulty_suffix, st.session_state.parsed_data_dict[current_view_diff], st.session_state.audio_cache_dict[current_view_diff], difficulty=current_view_diff)
        if zip_data:
            st.download_button(
                label=f"📦 {current_view_diff} 개별 파일 다운로드 (ZIP)",
                data=zip_data,
                file_name=f"{difficulty_suffix}_individual_files.zip",
                mime="application/octet-stream",
                use_container_width=True,
                key=f"btn_dl_individual_{current_view_diff}"
            )
    with col2:
        scene_groups = {}
        added_line_keys = set()
        for item in st.session_state.parsed_data_dict[current_view_diff]:
            scene = item['scene']
            lk = f"{scene}_{item['line']}"
            if lk in added_line_keys:
                continue
            if scene not in scene_groups:
                scene_groups[scene] = []
            if lk in st.session_state.audio_cache_dict[current_view_diff]:
                scene_groups[scene].append(st.session_state.audio_cache_dict[current_view_diff][lk])
                added_line_keys.add(lk)
        if scene_groups:
            current_cache_size = len(st.session_state.audio_cache_dict[current_view_diff])
            cached_size = st.session_state.merged_scene_cache_size.get(current_view_diff, 0)
            if current_cache_size != cached_size or not st.session_state.merged_scene_cache.get(current_view_diff):
                merged_cache = {s: audio_engine.merge_audio(al) for s, al in scene_groups.items() if al}
                # mBook은 모든 씬을 하나의 파일로 합침
                if current_view_diff == "mBook" and len(merged_cache) > 1:
                    merged_cache = {"mBook": audio_engine.concat_audio(list(merged_cache.values()))}
                st.session_state.merged_scene_cache[current_view_diff] = merged_cache
                st.session_state.merged_scene_cache_size[current_view_diff] = current_cache_size
            else:
                merged_cache = st.session_state.merged_scene_cache[current_view_diff]
            first_book_id = st.session_state.parsed_data_dict[current_view_diff][0].get('book_id', '') if st.session_state.parsed_data_dict[current_view_diff] else ""
            zip_data_merged = exporter.create_merged_zip(difficulty_suffix, merged_cache, book_id=first_book_id, difficulty=current_view_diff)
            st.download_button(
                label=f"🎞️ {current_view_diff} 씬별 병합 다운로드 (ZIP)",
                data=zip_data_merged,
                file_name=f"{difficulty_suffix}_merged_scenes.zip",
                mime="application/octet-stream",
                use_container_width=True,
                key=f"btn_dl_merged_{current_view_diff}"
            )


# 사이드바: 기본 설정 및 입력 UI
with st.sidebar:
    st.title("⚙️ 설정")
    
    st.subheader("ElevenLabs 설정")
    api_key_input = st.text_input("ElevenLabs API Key", value=st.session_state.api_key, type="password")
    if st.button("API Key 적용"):
        if api_key_input:
            clean_key = api_key_input.strip()
            st.session_state.api_key = clean_key
            _save_key_to_env("ELEVENLABS_API_KEY", clean_key)
            with st.spinner("연결 테스트 중..."):
                check_result = audio_engine.check_api_key(clean_key)
                if not check_result["success"]:
                    st.error(f"⚠️ 연결 테스트 실패: {check_result['error']}")
                    st.info("API Key 설정에서 'Read Voices' 또는 'Read Models' 권한이 포함되어 있는지 확인해 주세요.")
                else:
                    voices = audio_engine.get_voices(clean_key)
                    if isinstance(voices, dict) and "error" in voices:
                        st.warning(f"🔔 목소리 목록을 가져올 수 없습니다. (권한 부족 가능성)\n{voices['error']}")
                        st.info("목소리를 선택할 수 없지만, 생성 단계에서 직접 Voice ID를 입력하여 시도할 수 있습니다.")
                        st.session_state.voices = {"수동 입력": "manual"}
                    else:
                        st.session_state.voices = voices
                        sub = audio_engine.get_subscription_info(clean_key)
                        if sub["success"]:
                            st.session_state.subscription_info = sub
                        else:
                            st.session_state.subscription_info = None
                            st.warning(f"⚠️ 구독 정보를 불러올 수 없습니다: {sub.get('error', '알 수 없는 오류')} (텍스트 리밋/보이스 슬롯 현황이 표시되지 않을 수 있습니다.)")
                        st.success("✅ 인증 성공 및 목소리 목록 로드 완료!")
                        st.balloons()
        else:
            st.warning("API Key를 입력해 주세요.")

    # 보이스 슬롯 현황 표시
    if st.session_state.api_key and st.session_state.voices:
        sub = st.session_state.get("subscription_info")
        if sub and sub.get("success"):
            used = len([v for v in st.session_state.voices.values() if isinstance(v, dict)])
            limit = sub.get("voice_limit", 0)
            ratio = used / limit if limit > 0 else 0
            bar_color = "normal" if ratio < 0.8 else ("off" if ratio >= 1.0 else "off")
            st.caption("🎙️ 보이스 슬롯 현황")
            st.progress(min(ratio, 1.0))
            if ratio >= 1.0:
                st.error(f"슬롯 초과: {used} / {limit} — 새 보이스 추가 시 기존 보이스가 삭제됩니다.")
            elif ratio >= 0.8:
                st.warning(f"슬롯: {used} / {limit} — 곧 한도에 도달합니다.")
            else:
                st.caption(f"사용 중: {used} / {limit}")
            char_used = sub.get("character_count", 0)
            char_limit = sub.get("character_limit", 0)
            if char_limit > 0:
                st.caption(f"📝 이번 달 글자 수: {char_used:,} / {char_limit:,}")
            else:
                st.caption(f"📝 이번 달 글자 수: {char_used:,} (한도 정보 없음)")

    st.divider()
    st.subheader("Gemini 설정")
    gemini_key_input = st.text_input("Gemini API Key", value=st.session_state.gemini_api_key, type="password")
    if st.button("Gemini Key 적용"):
        if gemini_key_input:
            clean_gemini_key = gemini_key_input.strip()
            st.session_state.gemini_api_key = clean_gemini_key
            _save_key_to_env("GEMINI_API_KEY", clean_gemini_key)
            with st.spinner("Gemini 연결 확인 중..."):
                try:
                    from google import genai
                    client = genai.Client(api_key=clean_gemini_key)
                    models = list(client.models.list())
                    # SDK 버전에 따라 속성명이 다를 수 있으므로 안전하게 필터링
                    model_names = []
                    for m in models:
                        methods = getattr(m, 'supported_methods', getattr(m, 'supported_generation_methods', []))
                        if not methods or "generateContent" in str(methods):
                            model_names.append(m.name)
                    
                    # 지능형 모델 선택: 해당 키가 지원하는 가장 좋은 모델 찾기
                    preferred_models = [
                        "models/gemini-1.5-flash", 
                        "models/gemini-1.5-pro",
                        "models/gemini-2.0-flash-exp",
                        "models/gemini-1.0-pro"
                    ]
                    
                    best_model = None
                    for pm in preferred_models:
                        if any(pm == name for name in model_names):
                            best_model = pm
                            break
                    
                    if not best_model and model_names:
                        # 선호 목록에 없으면 사용 가능한 모델 중 첫 번째 선택
                        best_model = model_names[0]
                    
                    if best_model:
                        st.session_state.gemini_model = best_model
                        st.success(f"✅ Gemini 인증 성공! 현재 키에 최적화된 모델({best_model})이 설정되었습니다.")
                    else:
                        # 폴백: 직접 지정
                        st.session_state.gemini_model = "models/gemini-1.5-flash"
                        st.warning(f"⚠️ 사용 가능한 모델을 찾지 못해 기본 모델({st.session_state.gemini_model})을 설정합니다.")
                except Exception as e:
                    st.error(f"❌ Gemini 연결 테스트 실패: {str(e)}")
                    st.info("API 키가 정확한지, 혹은 할당량(limit)이 0이 아닌지 확인해 주세요.")
        else:
            st.warning("Gemini API Key를 입력해 주세요.")

    st.divider()
    # 사이드바의 난이도는 "현재 뷰어에서 볼 난이도"를 결정함
    current_view_diff = st.radio("필요한 음원 선택", DIFFICULTIES)
    difficulty_suffix = {"Normal": "N_A", "Easy": "E_A", "Difficult": "D_A", "mBook": "A"}.get(current_view_diff, "N_A")
    story_no = "" # UI에서 제거됨

    # 세션 복원 알림
    if st.session_state.pop("_restored_from_backup", False):
        st.success("이전 작업이 자동 복원되었습니다.", icon="✅")


# 매 렌더마다 자동 저장 (파싱된 데이터가 있을 때만)
_autosave()

_tab_dub, _tab_narr = st.tabs(['🎙️ 대본 더빙', '🎬 나레이션 스튜디오'])

import narration_studio as _narr_mod
with _tab_narr:
    _narr_mod.render()

with _tab_dub:
    st.title("🎙️ 동화 대본 자동 더빙 및 편집 에이전트")

    st.divider()
    st.header("Step 1: 대본 파일 업로드 및 AI 분석")
    import pandas as pd
    uploaded_scripts = st.file_uploader("대본 파일 업로드 (CSV 또는 Excel) - 최대 4개", type=['csv', 'xlsx', 'xls'], key="script_uploader", accept_multiple_files=True)

    if uploaded_scripts:
        # 파일명 기반 자동 매핑 및 수동 조정 UI (Normal > Easy > Difficult > mBook 고정 순서)
        st.subheader("필요한 음원별 매핑")
        file_mapping = {}

        file_options = ["(없음)"] + [f.name for f in uploaded_scripts]
        file_by_name = {f.name: f for f in uploaded_scripts}

        # 파일명으로 자동 추측
        def _guess_file(diff):
            hints = {
                "Normal":   lambda n: "easy" not in n and "diff" not in n and "hard" not in n and "mbook" not in n,
                "Easy":     lambda n: "easy" in n or "쉬움" in n,
                "Difficult":lambda n: "diff" in n or "hard" in n or "어려움" in n,
                "mBook":    lambda n: "mbook" in n,
            }
            check = hints.get(diff, lambda n: False)
            for f in uploaded_scripts:
                if check(f.name.lower()):
                    return f.name
            return "(없음)"

        cols = st.columns(4)
        for col, diff in zip(cols, DIFFICULTIES):
            with col:
                st.markdown(f"**{diff}**")
                default_file = _guess_file(diff)
                default_idx = file_options.index(default_file) if default_file in file_options else 0
                selected_name = st.selectbox(diff, file_options, index=default_idx, key=f"diff_map_{diff}", label_visibility="collapsed")
                if selected_name != "(없음)":
                    file_mapping[diff] = file_by_name[selected_name]

        if st.button("✨ 모든 대본 AI 분석하기", type="primary", use_container_width=True):
            if not file_mapping:
                st.warning("분석할 파일이 없습니다.")
            elif not st.session_state.get('gemini_api_key'):
                st.error("좌측 사이드바에서 Gemini API Key를 입력하고 '적용' 버튼을 눌러주세요.")
            else:
                best_model = st.session_state.get('gemini_model', 'models/gemini-1.5-flash')
                gemini_key = st.session_state.gemini_api_key

                # Step 1: 모든 파일 읽기
                dfs = {}
                for diff, f in file_mapping.items():
                    try:
                        if f.name.endswith('.csv'):
                            df = pd.read_csv(f)
                        else:
                            df = pd.read_excel(f)
                        required_cols = ['ID', 'Key', 'Text']
                        missing = [c for c in required_cols if c not in df.columns]
                        if missing:
                            st.error(f"'{f.name}' 파일에 필수 컬럼이 없습니다: {', '.join(missing)}")
                            continue
                        dfs[diff] = df
                    except Exception as e:
                        st.error(f"'{f.name}' 파일 읽기 실패: {str(e)}")

                if not dfs:
                    st.warning("분석할 파일이 없습니다.")
                else:
                    try:
                        # Step 2: 첫 번째 파일로 캐릭터 추출 (1회 풀 분석)
                        first_diff = list(dfs.keys())[0]
                        first_script = "\n".join(dfs[first_diff]['Text'].dropna().astype(str).tolist())
                        with st.spinner("Gemini AI가 캐릭터를 분석 중입니다... (1단계)"):
                            char_res = llm_helper.extract_script_metadata_via_gemini(gemini_key, first_script, model_name=best_model)

                        if not char_res['success']:
                            st.error(f"캐릭터 분석 실패: {char_res.get('error', '알 수 없는 오류')}")
                        else:
                            all_characters_data = {
                                c_name: c_info for c_name, c_info in char_res['characters'].items()
                                if c_name.strip().lower() not in ('내레이션', 'narration', 'narrator')
                            }
                            known_char_names = list(char_res['characters'].keys())
                            segment_results = {first_diff: char_res}
                            other_items = [(diff, df) for diff, df in dfs.items() if diff != first_diff]

                            # Step 3: 나머지 파일 세그먼트 병렬 분석
                            if other_items:
                                def _annotate_task(item):
                                    diff, df = item
                                    script_text = "\n".join(df['Text'].dropna().astype(str).tolist())
                                    return diff, llm_helper.annotate_segments_via_gemini(
                                        gemini_key, script_text, known_char_names, model_name=best_model
                                    )

                                with st.spinner(f"Gemini AI가 나머지 {len(other_items)}개 대본을 병렬 분석 중입니다... (2단계)"):
                                    with concurrent.futures.ThreadPoolExecutor(max_workers=len(other_items)) as executor:
                                        futures = {executor.submit(_annotate_task, item): item[0] for item in other_items}
                                        for future in concurrent.futures.as_completed(futures):
                                            diff, res = future.result()
                                            segment_results[diff] = res

                            # Step 4: 결과 저장
                            success_count = 0
                            for diff, df in dfs.items():
                                res = segment_results.get(diff)
                                if res and res['success']:
                                    parsed, _ = processor.parse_dataframe(df, char_res['characters'], ai_metadata=res['segments_metadata'])
                                    st.session_state.parsed_data_dict[diff] = parsed
                                    st.session_state.voice_mappings_dict[diff] = {item['segment_id']: "" for item in parsed}
                                    st.session_state.script_parsed_dict[diff] = True
                                    success_count += 1
                                else:
                                    st.error(f"[{diff}] 세그먼트 분석 실패: {res.get('error', '알 수 없는 오류') if res else '결과 없음'}")

                            if success_count > 0:
                                st.session_state.characters = all_characters_data
                                st.session_state.character_voice_mappings = {name: "" for name in all_characters_data}
                                st.session_state.character_confirmed = False
                                st.success(f"✅ {success_count}개 난이도 대본 분석 및 캐릭터 통합 완료!")
                                st.rerun()
                            else:
                                st.warning("분석에 성공한 파일이 없습니다. 설정을 확인해 주세요.")
                    except Exception as e:
                        error_trace = traceback.format_exc()
                        st.error(f"처리 중 오류 발생: {str(e)}")
                        with st.expander("상세 에러 로그 확인"):
                            st.code(error_trace)
                            if 'res' in locals():
                                st.write("Debug - res['characters'] type:", type(res.get('characters')))
                                st.write("Debug - res['characters'] value:", res.get('characters'))
                            if 'df' in locals():
                                st.write("Debug - df type:", type(df))
                                if hasattr(df, 'columns'):
                                    st.write("Debug - df columns:", list(df.columns))

    # 2. 보이스 설정 (내레이션 + 캐릭터 통합)
    if any(st.session_state.script_parsed_dict.values()):
            st.divider()
            st.header("2. 보이스 설정")

            # 2-1. 내레이션 설정
            st.subheader("🎙️ 내레이션 보이스")
            if not st.session_state.voices:
                st.info("사이드바에서 ElevenLabs API Key를 입력하세요.")
            else:
                if 'all_narration_voice_id' not in st.session_state:
                    st.session_state.all_narration_voice_id = ""

                n_col1, n_col2 = st.columns([3, 1])
                with n_col1:
                    new_n_id = voice_selector_ui("모두 적용할 내레이션 보이스", st.session_state.all_narration_voice_id, st.session_state.voices, "all_narration")
                    if new_n_id != st.session_state.all_narration_voice_id:
                        st.session_state.all_narration_voice_id = new_n_id
                        st.rerun()
                with n_col2:
                    if st.button("내레이션 일괄 적용", use_container_width=True):
                        if st.session_state.all_narration_voice_id:
                            for d in DIFFICULTIES:
                                for item in st.session_state.parsed_data_dict[d]:
                                    if item['type'] == '내레이션':
                                        st.session_state.voice_mappings_dict[d][item['segment_id']] = st.session_state.all_narration_voice_id
                            st.success("모든 난이도에 내레이션 보이스가 일괄 적용되었습니다.")
                            st.rerun()

            st.write("---")

            # 2-2. 캐릭터별 설정
            st.subheader("👥 캐릭터 보이스")
            if not st.session_state.characters:
                st.info("추출된 캐릭터가 없습니다. '+' 버튼으로 추가하거나 대본을 보완해 보세요.")

            # 8열 그리드
            char_cols = st.columns(8)

            # 캐릭터 카드 (내레이션은 위 섹션에서 처리하므로 제외)
            _NARRATION_NAMES = {'내레이션', 'narration', 'narrator'}
            for i, (name, info) in enumerate((k, v) for k, v in st.session_state.characters.items() if k.strip().lower() not in _NARRATION_NAMES):
                with char_cols[i % 8]:
                    with st.expander(f"👤 {name}", expanded=True):
                        new_name = st.text_input(f"이름", value=name, key=f"edit_char_{name}", label_visibility="collapsed")
                        if new_name != name:
                            if new_name and new_name not in st.session_state.characters:
                                st.session_state.characters[new_name] = st.session_state.characters.pop(name)
                                st.session_state.character_voice_mappings[new_name] = st.session_state.character_voice_mappings.pop(name, "")
                                for d in DIFFICULTIES:
                                    for item in st.session_state.parsed_data_dict[d]:
                                        if item['character'] == name:
                                            item['character'] = new_name
                                st.rerun()

                        st.caption(f"{info.get('gender', '중성')} | {info.get('age', '성인')} | {info.get('tone', '보통')}")
                        if info.get('description'):
                            st.info(info['description'])

                        if st.session_state.voices:
                            current_v = st.session_state.character_voice_mappings.get(new_name, "")
                            chosen_v = voice_selector_ui("보이스", current_v, st.session_state.voices, f"v_char_{new_name}", char_info=info, char_name=new_name)
                            if chosen_v != current_v:
                                st.session_state.character_voice_mappings[new_name] = chosen_v
                                for d in DIFFICULTIES:
                                    for item in st.session_state.parsed_data_dict[d]:
                                        if item.get('character') == new_name:
                                            st.session_state.voice_mappings_dict[d][item['segment_id']] = chosen_v
                                st.rerun()

                            if st.button("적용", key=f"apply_{new_name}", use_container_width=True):
                                if chosen_v:
                                    for d in DIFFICULTIES:
                                        for item in st.session_state.parsed_data_dict[d]:
                                            if item.get('character') == new_name:
                                                st.session_state.voice_mappings_dict[d][item['segment_id']] = chosen_v
                                    st.rerun()

                        if st.button("삭제", key=f"del_{new_name}", type="secondary", use_container_width=True):
                            st.session_state.characters.pop(new_name)
                            st.session_state.character_voice_mappings.pop(new_name, None)
                            for d in DIFFICULTIES:
                                for item in st.session_state.parsed_data_dict[d]:
                                    if item['character'] == new_name:
                                        item['character'] = "내레이션"
                            st.rerun()

            # 수동 추가 카드
            next_i = len(st.session_state.characters)
            with char_cols[next_i % 8]:
                with st.container(border=True):
                    st.write("<div style='text-align: center; font-size: 20px;'>➕</div>", unsafe_allow_html=True)
                    new_c_name = st.text_input("이름", key="plus_char_name", placeholder="추가", label_visibility="collapsed")
                    if st.button("추가", key="plus_char_btn", use_container_width=True):
                        if new_c_name and new_c_name not in st.session_state.characters and new_c_name.strip().lower() not in ('내레이션', 'narration', 'narrator'):
                            st.session_state.characters[new_c_name] = {"name": new_c_name, "gender": "중성", "age": "성인", "tone": "보통"}
                            st.session_state.character_voice_mappings[new_c_name] = ""
                            st.rerun()
                        elif new_c_name.strip().lower() in ('내레이션', 'narration', 'narrator'):
                            st.warning("내레이션은 위의 '내레이션 보이스' 섹션에서 설정하세요.")

            st.divider()
            if not st.session_state.get('character_confirmed', False):
                if st.button("✅ 보이스 설정 완료 및 다음 단계로", type="primary", use_container_width=True):
                    st.session_state.character_confirmed = True
                    st.rerun()
            else:
                if st.button("🔄 보이스 설정 수정하기", use_container_width=True):
                    st.session_state.character_confirmed = False
                    st.rerun()

    # 3. 세그먼트 상세 설정 및 편집 (보이스 확정 후 노출)
    if st.session_state.parsed_data_dict[current_view_diff] and st.session_state.get('character_confirmed'):
        st.write("---")
        st.header(f"3. 세그먼트 상세 설정 및 편집 ({current_view_diff})")
        h_cols = st.columns([0.6, 1.1, 1.5, 4.3, 3.5, 1.0])
        h_cols[0].markdown("**장면**")
        h_cols[1].markdown("**순서**")
        h_cols[2].markdown("**캐릭터**")
        h_cols[3].markdown("**스크립트 (수정 시 엔터/빈 곳 클릭)**")
        h_cols[4].markdown("**보이스 설정**")
        h_cols[5].markdown("**추가/삭제**")
        st.write("---")

        # 페이지네이션
        _PAGE_SIZE = 15
        _all_segs = st.session_state.parsed_data_dict[current_view_diff]
        _total = len(_all_segs)
        _total_pages = max(1, (_total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        _cur_page = min(st.session_state.seg_page.get(current_view_diff, 0), _total_pages - 1)
        st.session_state.seg_page[current_view_diff] = _cur_page

        _p_cols = st.columns([1, 3, 1])
        if _p_cols[0].button("◀ 이전", disabled=(_cur_page == 0), key="seg_prev"):
            st.session_state.seg_page[current_view_diff] = _cur_page - 1
            st.rerun()
        _p_cols[1].markdown(f"<div style='text-align:center'><b>{_cur_page + 1} / {_total_pages} 페이지</b> &nbsp;(총 {_total}줄)</div>", unsafe_allow_html=True)
        if _p_cols[2].button("다음 ▶", disabled=(_cur_page >= _total_pages - 1), key="seg_next"):
            st.session_state.seg_page[current_view_diff] = _cur_page + 1
            st.rerun()

        _start = _cur_page * _PAGE_SIZE
        # 라인별 설정
        for i, item in enumerate(_all_segs[_start:_start + _PAGE_SIZE], start=_start):
            key = item['segment_id']
            cols = st.columns([0.6, 1.1, 1.5, 4.3, 3.5, 1.0])

            # 1. 장면
            cols[0].write(f"**{item.get('scene_num', item['scene'])}**")

            # 2. 순서 (Sequence)
            with cols[1]:
                st.write(f"**{item.get('seq_num', item['line'])}**")

            # 3. 캐릭터 수동 수정 (드롭다운)
            with cols[2]:
                char_options = list(st.session_state.characters.keys())
                if "내레이션" not in char_options: char_options.append("내레이션")
                current_char = item['character']

                # 감정(Mood) 표시용 뱃지 스타일 정의
                mood_colors = {
                    "Neutral": "gray", "Happy": "green", "Sad": "blue", 
                    "Angry": "red", "Excited": "orange", "Whispering": "purple"
                }
                mood = item.get('mood', 'Neutral')
                m_color = mood_colors.get(mood, "gray")

                st.markdown(f'<span style="background-color: {m_color}22; color: {m_color}; padding: 2px 6px; border-radius: 4px; border: 1px solid {m_color}44; font-size: 0.8em; margin-bottom: 4px; display: inline-block;">Mood: {mood}</span>', unsafe_allow_html=True)
                if current_char not in char_options:
                    char_options.insert(0, current_char)

                selected_char = st.selectbox(f"Char_{key}", options=char_options, index=char_options.index(current_char), key=f"char_select_{key}", label_visibility="collapsed")

                if selected_char != current_char:
                    st.session_state.parsed_data_dict[current_view_diff][i]['character'] = selected_char
                    # 캐릭터가 바뀌면 해당 캐릭터에게 지정된 보이스가 있는지 확인하여 자동 적용
                    if selected_char == "내레이션" and st.session_state.get('all_narration_voice_id'):
                        st.session_state.voice_mappings_dict[current_view_diff][key] = st.session_state.all_narration_voice_id
                    elif selected_char in st.session_state.character_voice_mappings:
                        char_voice = st.session_state.character_voice_mappings[selected_char]
                        if char_voice:
                            st.session_state.voice_mappings_dict[current_view_diff][key] = char_voice
                    st.rerun()

            # 4. 스크립트 수동 수정 (대사의 경우 따옴표 포함)
            with cols[3]:
                raw_text = item['text']
                # 따옴표 자동 추가/제거 로직 제거 (원본 데이터 유지)
                new_text = st.text_area(f"Text_{key}", value=raw_text, key=f"text_input_{key}", label_visibility="collapsed", height=68)

                if new_text != item['text']:
                    st.session_state.parsed_data_dict[current_view_diff][i]['text'] = new_text

            # 5. 보이스 설정
            current_voice_id = st.session_state.voice_mappings_dict[current_view_diff].get(key, "")
            with cols[4]:
                if st.session_state.voices:
                    chosen_id = voice_selector_ui(f"{item['type']} {key}", current_voice_id, st.session_state.voices, f"row_{key}", char_info=st.session_state.characters.get(item['character']), char_name=item['character'])
                    if chosen_id != current_voice_id:
                        st.session_state.voice_mappings_dict[current_view_diff][key] = chosen_id
                        st.rerun()
                else:
                    st.write("API Key 필요")

            # 6. 추가 (+) 버튼
            with cols[5]:
                if st.button("➕", key=f"add_{key}", help="이 대사 아래에 빈 행 추가"):
                    import uuid
                    new_id = str(uuid.uuid4())[:8]
                    new_item = {
                        'scene': item['scene'],
                        'line': item['line'],
                        'scene_num': item.get('scene_num', 'SC00'),
                        'seq_num': item.get('seq_num', 'ST00'),
                        'book_id': item.get('book_id', ''),
                        'audio_type': item.get('audio_type', 'N'),
                        'seg_idx': 0,
                        'type': '대사',
                        'character': item['character'],
                        'text': '',
                        'mood': 'Neutral',
                        'segment_id': new_id
                    }
                    st.session_state.parsed_data_dict[current_view_diff].insert(i + 1, new_item)
                    st.session_state.voice_mappings_dict[current_view_diff][new_id] = current_voice_id
                    st.rerun()

                if st.button("🗑️", key=f"del_row_{key}", help="이 행 삭제"):
                    st.session_state.parsed_data_dict[current_view_diff].pop(i)
                    st.session_state.voice_mappings_dict[current_view_diff].pop(key, None)
                    st.rerun()

        # 4. 음원 생성 및 미리보기 섹션
        st.divider()
        st.header("4. 음원 생성 및 미리보기")

        # 속도 조절 모드 선택 복구
        speed_mode = st.radio("🚀 속도 조절 모드", ["일괄 조정", "개별 조정(보이스/내레이션)"], horizontal=True)

        if speed_mode == "일괄 조정":
            bulk_speed = st.slider("전체 발화 속도", 0.7, 1.5, st.session_state.speed_settings.get("default", 1.0), 0.1, format="%.1fx")
            # 모든 항목의 속도를 동일하게 설정
            st.session_state.speed_settings["default"] = bulk_speed
            # 실제 생성 시 사용할 개별 캐릭터 설정에도 일괄 반영
            st.session_state.speed_settings["내레이션"] = bulk_speed
            used_chars = sorted(list(set([item['character'] for item in st.session_state.parsed_data_dict[current_view_diff] if item['character'] != "내레이션"])))
            for char in used_chars:
                st.session_state.speed_settings[char] = bulk_speed

        else:
            # 개별 조정 모드
            used_chars = sorted(list(set([item['character'] for item in st.session_state.parsed_data_dict[current_view_diff] if item['character'] != "내레이션"])))
            st.write("각 보이스별 발화 속도를 개별 설정하세요.")

            # 슬라이더들을 가로 그리드로 배치
            cols = st.columns(4)
            with cols[0]:
                st.session_state.speed_settings["내레이션"] = st.slider("🎙️ 내레이션", 0.7, 1.5, st.session_state.speed_settings.get("내레이션", 1.0), 0.1, format="%.1fx")

            for i, char in enumerate(used_chars):
                col_idx = (i + 1) % 4
                with cols[col_idx]:
                    st.session_state.speed_settings[char] = st.slider(f"🎭 {char}", 0.7, 1.5, st.session_state.speed_settings.get(char, 1.0), 0.1, format="%.1fx")
                if (i + 1) % 4 == 3 and i < len(used_chars) - 1:
                    cols = st.columns(4)

        # 미리듣기 샘플 생성 구역
        st.write("---")
        col_sample1, col_sample2 = st.columns([1, 2])
        with col_sample1:
            if st.button("🎧 속도 미리듣기 샘플 생성"):
                if not st.session_state.api_key:
                    st.error("API Key를 먼저 입력해 주세요.")
                elif not st.session_state.parsed_data_dict[current_view_diff]:
                    st.warning(f"'{current_view_diff}' 대본 분석을 먼저 진행해 주세요.")
                else:
                    with st.spinner("캐릭터별 실제 대사로 샘플 생성 중..."):
                        # 대상 캐릭터 목록 (내레이션 + 실제 대본의 캐릭터들)
                        sample_chars = ["내레이션"] + sorted(list(set([item['character'] for item in st.session_state.parsed_data_dict[current_view_diff] if item['character'] != "내레이션"])))

                        found_any = False
                        # 한 줄에 2개씩 배치
                        for i in range(0, len(sample_chars), 2):
                            cols_pre = st.columns(2)
                            row_chars = sample_chars[i:i+2]

                            for j, char in enumerate(row_chars):
                                voice_id = st.session_state.get('all_narration_voice_id') if char == "내레이션" else st.session_state.character_voice_mappings.get(char)

                                if voice_id:
                                    char_line = next((item['text'] for item in st.session_state.parsed_data_dict[current_view_diff] if item['character'] == char), "설정된 대사가 없습니다.")
                                    found_any = True
                                    sample_audio = audio_engine.generate_audio(st.session_state.api_key, char_line, voice_id)

                                    if isinstance(sample_audio, bytes):
                                        target_speed = st.session_state.speed_settings.get(char, 1.0)
                                        final_sample = audio_engine.apply_speed_control(sample_audio, target_speed)
                                        with cols_pre[j]:
                                            st.write(f"**{char}** ({target_speed}x)")
                                            st.caption(f"\"{char_line[:40]}...\"" if len(char_line) > 40 else f"\"{char_line}\"")
                                            st.audio(final_sample, format="audio/mpeg")
                                    else:
                                        with cols_pre[j]:
                                            st.error(f"{char} 생성 실패")

                        if not found_any:
                            st.warning("보이스가 지정된 캐릭터가 없습니다. Step 2에서 보이스를 먼저 설정해 주세요.")
                        else:
                            st.success("실제 대사 기반 샘플 생성 완료!")

        st.info("💡 팁: 캐릭터의 성격(톤)에 맞춰 목소리의 감정 표현이 자동으로 미세 조정됩니다.")

        def _generate_for_difficulties(target_diffs):
            """선택한 난이도 목록에 대해 음원을 생성하고 캐시에 저장합니다."""
            import time
            progress_bar = st.progress(0)
            status_text = st.empty()
            total_lines = sum(
                len(set(f"{item['scene']}_{item['line']}" for item in st.session_state.parsed_data_dict[d]))
                for d in target_diffs
            )
            processed = 0
            generation_errors = []

            for d in target_diffs:
                status_text.text(f"[{d}] 음원 생성 중... ({processed}/{total_lines})")

                lines_to_process = {}
                for item in st.session_state.parsed_data_dict[d]:
                    lk = f"{item['scene']}_{item['line']}"
                    lines_to_process.setdefault(lk, []).append(item)

                for line_key, segments in lines_to_process.items():
                    segment_audios = []
                    for seg in segments:
                        voice_id = st.session_state.voice_mappings_dict[d].get(seg['segment_id'])
                        if not voice_id:
                            cname = seg.get('character', '')
                            voice_id = (st.session_state.get('all_narration_voice_id', '')
                                        if cname == '내레이션'
                                        else st.session_state.character_voice_mappings.get(cname, ''))
                        if not voice_id:
                            continue

                        preset = MOOD_PRESETS.get(seg.get('mood', 'Neutral'), MOOD_PRESETS['Neutral'])
                        audio_bytes = audio_engine.generate_audio(
                            st.session_state.api_key, seg['text'], voice_id,
                            stability=preset['stability'],
                            similarity_boost=preset['similarity_boost'],
                            style=preset['style']
                        )
                        if isinstance(audio_bytes, bytes):
                            spd = st.session_state.speed_settings.get(seg.get('character', '내레이션'), 1.0)
                            if spd != 1.0:
                                audio_bytes = audio_engine.apply_speed_control(audio_bytes, spd)
                            audio_bytes = audio_engine.normalize_audio(audio_bytes)
                            segment_audios.append(audio_bytes)
                        elif isinstance(audio_bytes, dict) and 'error' in audio_bytes:
                            err_msg = audio_bytes['error']
                            if '429' in err_msg or 'rate' in err_msg.lower():
                                generation_errors.append(f"[{d}] {line_key}: API 요청 한도 초과(429) — 잠시 후 다시 시도하세요.")
                            else:
                                generation_errors.append(f"[{d}] {seg.get('character','?')} / {line_key}: {err_msg}")
                        # 연속 API 호출 간 짧은 간격으로 ElevenLabs 응답 품질 보호
                        time.sleep(0.3)

                    if segment_audios:
                        st.session_state.audio_cache_dict[d][line_key] = audio_engine.merge_audio(segment_audios)

                    processed += 1
                    progress_bar.progress(processed / total_lines)

            st.session_state.generation_errors = generation_errors
            if generation_errors:
                status_text.text("생성 중 일부 오류가 발생했습니다.")
            else:
                status_text.text(f"음원 생성 완료!")
                st.balloons()
            st.rerun()

        # ── 현재 난이도 생성 (기본 동작) ──────────────────────────────
        total_lines_cur = len(set(f"{item['scene']}_{item['line']}" for item in st.session_state.parsed_data_dict[current_view_diff]))
        if st.button(f"✨ {current_view_diff} 음원 생성 ({total_lines_cur}문장)", type="primary", use_container_width=True):
            if not st.session_state.api_key:
                st.error("API Key가 필요합니다.")
            elif not st.session_state.script_parsed_dict[current_view_diff]:
                st.warning(f"{current_view_diff} 대본이 아직 분석되지 않았습니다.")
            else:
                _generate_for_difficulties([current_view_diff])

        # ── 전체 난이도 일괄 생성 (접힌 옵션) ────────────────────────
        with st.expander("Normal, Easy, Difficult, mBook 일괄 생성"):
            ready_diffs = [d for d in DIFFICULTIES if st.session_state.script_parsed_dict[d]]
            if not ready_diffs:
                st.info("분석 완료된 난이도가 없습니다.")
            else:
                total_all = sum(
                    len(set(f"{item['scene']}_{item['line']}" for item in st.session_state.parsed_data_dict[d]))
                    for d in ready_diffs
                )
                st.caption(f"분석 완료: {', '.join(ready_diffs)} — 총 {total_all}문장")
                if st.button("✨ Normal, Easy, Difficult, mBook 일괄 생성", use_container_width=True):
                    if not st.session_state.api_key:
                        st.error("API Key가 필요합니다.")
                    else:
                        _generate_for_difficulties(ready_diffs)

        # 생성 오류 표시 (rerun 이후에도 유지)
        if st.session_state.generation_errors:
            st.warning("⚠️ 일부 음원 생성 중 오류가 발생했습니다.")
            for err in st.session_state.generation_errors:
                st.error(err)
            if st.button("오류 메시지 닫기"):
                st.session_state.generation_errors = []
                st.rerun()

        # 오디오 플레이어 + 다운로드 (fragment로 부분 렌더링)
        audio_player_display(current_view_diff, difficulty_suffix)
