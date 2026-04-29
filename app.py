import streamlit as st
import processor
import audio_engine
import exporter
import json
import llm_helper
import moviepy as mp
import tempfile
import os
import io

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

# 세션 상태 초기화
if 'api_key' not in st.session_state:
    st.session_state.api_key = ""
if 'gemini_api_key' not in st.session_state:
    st.session_state.gemini_api_key = ""
if 'voices' not in st.session_state:
    st.session_state.voices = {}

# 난이도별 데이터 관리 (Normal, Easy, Difficult)
DIFFICULTIES = ["Normal", "Easy", "Difficult"]
if 'parsed_data_dict' not in st.session_state:
    st.session_state.parsed_data_dict = {d: [] for d in DIFFICULTIES}
if 'voice_mappings_dict' not in st.session_state:
    st.session_state.voice_mappings_dict = {d: {} for d in DIFFICULTIES}
if 'audio_cache_dict' not in st.session_state:
    st.session_state.audio_cache_dict = {d: {} for d in DIFFICULTIES}

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
    st.session_state.voice_mappings_dict = {d: {} for d in DIFFICULTIES}
    st.session_state.characters = {}
    st.session_state.character_voice_mappings = {}
    st.session_state.character_confirmed = False
    st.session_state.cloned_voice_id = None
    st.session_state.cloned_voice_bytes = None
    st.session_state.cloned_char_name = None

# 커스텀 보이스 셀렉터 헬퍼 함수
def voice_selector_ui(key_label, current_voice_id, voices_dict, container_key):
    """st.popover를 사용하여 검색 및 재생 기능이 포함된 커스텀 셀렉터를 렌더링합니다."""
    voice_names = list(voices_dict.keys())
    current_voice_name = next((name for name, data in voices_dict.items() if isinstance(data, dict) and data.get('id') == current_voice_id), "선택 안 함")
    if current_voice_id and current_voice_name == "선택 안 함" and current_voice_id != "manual":
        current_voice_name = f"수동 입력 ({current_voice_id})"

    with st.popover(f"🎙️ {current_voice_name}", use_container_width=True):
        st.write(f"**{key_label} 선택**")
        st.caption("닫으려면 팝오버 바깥쪽을 클릭하세요. (X 아이콘 없음)")
        search_query = st.text_input("보이스 검색", key=f"search_{container_key}", placeholder="이름으로 검색...").lower()
        
        filtered_voices = [name for name in voice_names if search_query in name.lower()]
        
        with st.container(height=300):
            # 기본 옵션들
            none_type = "primary" if current_voice_id == "" else "secondary"
            if st.button("선택 안 함", key=f"none_{container_key}", use_container_width=True, type=none_type):
                return ""
            
            manual_type = "primary" if current_voice_id == "manual" else "secondary"
            if st.button("➕ 수동 ID 입력", key=f"manual_btn_{container_key}", use_container_width=True, type=manual_type):
                return "manual"
            
            st.divider()
            
            for name in filtered_voices:
                v_data = voices_dict[name]
                v_id = v_data['id']
                v_preview = v_data.get('preview')
                
                is_selected = (v_id == current_voice_id)
                btn_type = "primary" if is_selected else "secondary"
                
                col_name, col_play, col_sel = st.columns([5.5, 1.5, 3])
                col_name.write(name)
                
                if v_preview:
                    if col_play.button("🔊", key=f"p_{container_key}_{v_id}", help="샘플 듣기"):
                        st.audio(v_preview, format="audio/mpeg", autoplay=True)
                elif v_id == st.session_state.get('cloned_voice_id') and st.session_state.get('cloned_voice_bytes'):
                    if col_play.button("🔊", key=f"p_{container_key}_{v_id}", help="복제된 원본 샘플 듣기"):
                        st.audio(st.session_state.cloned_voice_bytes, format="audio/mpeg", autoplay=True)
                
                if col_sel.button("선택" if not is_selected else "✅", key=f"s_{container_key}_{v_id}", type=btn_type, use_container_width=True):
                    return v_id
    
    return current_voice_id

# 사이드바: 기본 설정 및 입력 UI
with st.sidebar:
    st.title("⚙️ 설정")
    
    st.subheader("ElevenLabs 설정")
    api_key_input = st.text_input("ElevenLabs API Key", value=st.session_state.api_key, type="password")
    if st.button("API Key 적용"):
        if api_key_input:
            clean_key = api_key_input.strip()
            st.session_state.api_key = clean_key
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
                        st.success("✅ 인증 성공 및 목소리 목록 로드 완료!")
                        st.balloons()
        else:
            st.warning("API Key를 입력해 주세요.")

    st.divider()
    st.subheader("Gemini 설정")
    gemini_key_input = st.text_input("Gemini API Key", value=st.session_state.gemini_api_key, type="password")
    if st.button("Gemini Key 적용"):
        if gemini_key_input:
            clean_gemini_key = gemini_key_input.strip()
            st.session_state.gemini_api_key = clean_gemini_key
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
    current_view_diff = st.radio("표시할 난이도 선택", DIFFICULTIES)
    difficulty_suffix = {"Normal": "N_A", "Easy": "E_A", "Difficult": "D_A"}.get(current_view_diff, "N_A")
    story_no = "" # UI에서 제거됨

st.title("🎙️ 동화 대본 자동 더빙 및 편집 에이전트")

# Step 1: 에셋 생성 (보이스 클로닝)
st.header("Step 1: 캐릭터 목소리 복제하기 (에셋 생성)")
with st.container(border=True):
    uploaded_file = st.file_uploader("캐릭터 인사 영상(mp4) 또는 음성(mp3, wav) 업로드", type=['mp4', 'mp3', 'wav'], key="voice_uploader")
    
    if uploaded_file:
        col1, col2 = st.columns([2, 1])
        with col1:
            char_name = st.text_input("복제할 캐릭터 이름", placeholder="예: 아기돼지, 늑대 등")
        
        if st.button("✨ 목소리 에셋으로 저장"):
            if not char_name:
                st.warning("캐릭터 이름을 입력해 주세요.")
            elif not st.session_state.api_key:
                st.error("사이드바에서 ElevenLabs API Key를 먼저 설정해 주세요.")
            else:
                with st.spinner("1단계: 배경음악 및 노이즈 제거 중... (Audio Isolation)"):
                    try:
                        # 오디오 추출 처리
                        file_ext = os.path.splitext(uploaded_file.name)[1].lower()
                        raw_audio_bytes = None
                        
                        if file_ext == '.mp4':
                            # 임시 파일로 저장 후 처리
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_mp4:
                                tmp_mp4.write(uploaded_file.getvalue())
                                tmp_mp4_path = tmp_mp4.name
                            
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_mp3:
                                tmp_mp3_path = tmp_mp3.name
                                
                            video = mp.VideoFileClip(tmp_mp4_path)
                            video.audio.write_audiofile(tmp_mp3_path, logger=None)
                            
                            with open(tmp_mp3_path, "rb") as f:
                                raw_audio_bytes = f.read()
                            
                            video.close()
                            # 임시 파일 삭제
                            os.unlink(tmp_mp4_path)
                            os.unlink(tmp_mp3_path)
                        else:
                            raw_audio_bytes = uploaded_file.getvalue()
                        
                        # Audio Isolation API 연동 (배경음악 제거)
                        isolation_res = audio_engine.isolate_audio(st.session_state.api_key, raw_audio_bytes)
                        if not isolation_res['success']:
                            st.error(f"오디오 정제 실패: {isolation_res['error']}")
                            st.stop()

                        clean_audio_bytes = isolation_res['audio_bytes']
                        st.info("🎨 오디오 정제 완료! 보이스 클로닝을 시작합니다...")

                        # ElevenLabs API 호출 (정제된 음성으로 클로닝)
                        with st.spinner("2단계: 정제된 목소리로 보이스 클로닝 중..."):
                            res = audio_engine.add_voice(st.session_state.api_key, char_name, clean_audio_bytes)
                            
                            if res['success']:
                                st.session_state.cloned_voice_id = res['voice_id']
                                st.session_state.cloned_voice_bytes = clean_audio_bytes # 정제된 목소리 저장
                                st.success(f"✅ '{char_name}' 목소리 정제 및 복제 완료! (ID: {res['voice_id']})")
                                
                                # 보이스 목록 새로고침
                                voices = audio_engine.get_voices(st.session_state.api_key)
                                if not isinstance(voices, dict) or "error" not in voices:
                                    st.session_state.voices = voices
                                    # 새 목소리를 캐릭터 맵핑에 미리 넣어둠 (Step 3에서 자동 선택되게)
                                    st.session_state.cloned_char_name = char_name
                                st.rerun()
                            else:
                                st.error(f"복제 실패: {res['error']}")
                    except Exception as e:
                        st.error(f"처리 중 오류 발생: {str(e)}")
        
        # 복제된 목소리 미리보기 추가
        if st.session_state.get('cloned_voice_id') and st.session_state.get('cloned_voice_bytes'):
            st.divider()
            st.write(f"🎧 **복제된 '{st.session_state.get('cloned_char_name', '캐릭터')}' 목소리 미리듣기 (정제본)**")
            st.audio(st.session_state.cloned_voice_bytes, format="audio/mpeg")

st.divider()
st.header("Step 2: 대본 파일 업로드 및 AI 분석")
import pandas as pd
uploaded_scripts = st.file_uploader("대본 파일 업로드 (CSV 또는 Excel) - 최대 3개", type=['csv', 'xlsx', 'xls'], key="script_uploader", accept_multiple_files=True)

if uploaded_scripts:
    # 파일명 기반 자동 매핑 및 수동 조정 UI
    st.subheader("파일별 난이도 매핑")
    file_mapping = {}
    
    cols = st.columns(len(uploaded_scripts))
    for idx, f in enumerate(uploaded_scripts):
        with cols[idx]:
            st.write(f"📄 {f.name}")
            # 파일명에 힌트가 있으면 자동 선택
            default_idx = 0
            fname_lower = f.name.lower()
            if "easy" in fname_lower or "쉬움" in fname_lower: default_idx = 1
            elif "diff" in fname_lower or "hard" in fname_lower or "어려움" in fname_lower: default_idx = 2
            
            selected_diff = st.selectbox(f"난이도 선택 ({idx})", DIFFICULTIES, index=default_idx, key=f"diff_map_{idx}", label_visibility="collapsed")
            file_mapping[selected_diff] = f

    if st.button("✨ 모든 대본 AI 분석하기"):
        if not file_mapping:
            st.warning("분석할 파일이 없습니다.")
        elif not st.session_state.get('gemini_api_key'):
            st.error("좌측 사이드바에서 Gemini API Key를 입력해 주세요.")
        else:
            all_characters = set()
            with st.spinner(f"Gemini AI가 모든 난이도 대본을 분석 중입니다..."):
                try:
                    for diff, f in file_mapping.items():
                        if f.name.endswith('.csv'):
                            df = pd.read_csv(f)
                        else:
                            df = pd.read_excel(f)
                            
                        required_cols = ['ID', 'Key', 'Text']
                        missing = [c for c in required_cols if c not in df.columns]
                        if missing:
                            st.error(f"'{f.name}' 파일에 필수 컬럼이 없습니다: {', '.join(missing)}")
                            continue
                            
                        script_text = "\n".join(df['Text'].dropna().astype(str).tolist())
                        
                        # AI 분석
                        best_model = st.session_state.get('gemini_model', 'models/gemini-1.5-flash')
                        res = llm_helper.extract_script_metadata_via_gemini(st.session_state.gemini_api_key, script_text, model_name=best_model)
                        
                        if res['success']:
                            # 캐릭터 목록 합치기
                            for c in res['characters']:
                                all_characters.add(c)
                            
                            # 대본 파싱
                            parsed, _ = processor.parse_dataframe(df, res['characters'], ai_metadata=res['segments_metadata'])
                            
                            # 난이도별 저장
                            st.session_state.parsed_data_dict[diff] = parsed
                            st.session_state.voice_mappings_dict[diff] = {item['segment_id']: "" for item in parsed}
                            st.session_state.script_parsed_dict[diff] = True
                            
                    # 통합 캐릭터 리스트 업데이트
                    st.session_state.characters = {c: {"gender": "중성", "age": "성인", "tone": "보통"} for c in all_characters}
                    st.session_state.character_voice_mappings = {name: "" for name in st.session_state.characters}
                    
                    # 복제된 보이스가 있다면 자동 매칭
                    if st.session_state.get('cloned_char_name') and st.session_state.get('cloned_voice_id'):
                        c_name = st.session_state.cloned_char_name
                        v_id = st.session_state.cloned_voice_id
                        if c_name in st.session_state.character_voice_mappings:
                            st.session_state.character_voice_mappings[c_name] = v_id
                            # 모든 난이도의 개별 세그먼트에도 적용
                            for d in DIFFICULTIES:
                                for item in st.session_state.parsed_data_dict[d]:
                                    if item.get('character') == c_name:
                                        st.session_state.voice_mappings_dict[d][item['segment_id']] = v_id

                    st.session_state.character_confirmed = False
                    st.success("✅ 모든 난이도 대본 분석 및 캐릭터 통합 완료!")
                    st.rerun()
                except Exception as e:
                    st.error(f"처리 중 오류 발생: {str(e)}")

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
        
        # 캐릭터 카드
        for i, (name, info) in enumerate(st.session_state.characters.items()):
            with char_cols[i % 8]:
                with st.expander(f"👤 {name}", expanded=True):
                    new_name = st.text_input(f"이름", value=name, key=f"edit_char_{name}", label_visibility="collapsed")
                    if new_name != name:
                        if new_name and new_name not in st.session_state.characters:
                            st.session_state.characters[new_name] = st.session_state.characters.pop(name)
                            st.session_state.character_voice_mappings[new_name] = st.session_state.character_voice_mappings.pop(name, "")
                            for item in st.session_state.parsed_data:
                                if item['character'] == name:
                                    item['character'] = new_name
                            st.rerun()

                    st.caption(f"{info.get('gender', '중성')} | {info.get('age', '성인')} | {info.get('tone', '보통')}")
                    if info.get('description'):
                        st.info(info['description'])
                    
                    if st.session_state.voices:
                        current_v = st.session_state.character_voice_mappings.get(new_name, "")
                        chosen_v = voice_selector_ui("보이스", current_v, st.session_state.voices, f"v_char_{new_name}")
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
                    if new_c_name and new_c_name not in st.session_state.characters:
                        st.session_state.characters[new_c_name] = {"name": new_c_name, "gender": "중성", "age": "성인", "tone": "보통"}
                        st.session_state.character_voice_mappings[new_c_name] = ""
                        st.rerun()

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

    # 라인별 설정
    for i, item in enumerate(st.session_state.parsed_data_dict[current_view_diff]):
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
                chosen_id = voice_selector_ui(f"{item['type']} {key}", current_voice_id, st.session_state.voices, f"row_{key}")
                if chosen_id != current_voice_id:
                    st.session_state.voice_mappings_dict[current_view_diff][key] = chosen_id
                    st.rerun()
            else:
                st.write("API Key 필요")
                
            if st.session_state.voice_mappings_dict[current_view_diff].get(key) == "manual":
                st.session_state.voice_mappings_dict[current_view_diff][key] = st.text_input(f"Voice ID 입력 ({key})", key=f"manual_input_{key}", placeholder="ElevenLabs Voice ID 입력")
        
        # 6. 추가 (+) 버튼
        with cols[5]:
            if st.button("➕", key=f"add_{key}", help="이 대사 아래에 빈 행 추가"):
                import uuid
                new_id = str(uuid.uuid4())[:8]
                new_item = {
                    'scene': item['scene'],
                    'line': item['line'], # 기존 ST 번호 그대로 유지
                    'type': '대사',
                    'character': item['character'],
                    'text': '',
                    'segment_id': new_id
                }
                st.session_state.parsed_data_dict[current_view_diff].insert(i + 1, new_item)
                st.session_state.voice_mappings_dict[current_view_diff][new_id] = current_voice_id
                st.rerun()
                
            if st.button("🗑️", key=f"del_row_{key}", help="이 행 삭제"):
                st.session_state.parsed_data_dict[current_view_diff].pop(i)
                st.session_state.voice_mappings_dict[current_view_diff].pop(key, None)
                st.rerun()

    # 속도 조절 세션 초기화
    if 'speed_settings' not in st.session_state:
        st.session_state.speed_settings = {"내레이션": 1.0}
    
    # 3. 음원 생성 및 미리보기 섹션
    st.divider()
    st.header("3. 음원 생성 및 미리보기")
    
    # 속도 조절 모드 선택
    speed_mode = st.radio("🚀 속도 조절 모드", ["일괄 조정", "개별 조정(보이스/내레이션)"], horizontal=True)
    
    if speed_mode == "일괄 조정":
        bulk_speed = st.slider("전체 발화 속도", 0.7, 1.5, 1.0, 0.1, format="%.1fx")
        # 모든 항목의 속도를 동일하게 설정
        st.session_state.speed_settings = {k: bulk_speed for k in st.session_state.speed_settings.keys()}
        st.session_state.speed_settings["default"] = bulk_speed
    else:
        # 현재 보고 있는 대본에서 실제 사용된 캐릭터 이름들 추출 (내레이션 제외)
        used_chars = sorted(list(set([item['character'] for item in st.session_state.parsed_data_dict[current_view_diff] if item['character'] != "내레이션"])))
        
        st.write("각 보이스별 속도를 개별 설정하세요.")
        cols = st.columns(len(used_chars) + 1)
        
        # 내레이션 조절
        with cols[0]:
            st.session_state.speed_settings["내레이션"] = st.slider("🎙️ 내레이션", 0.7, 1.5, st.session_state.speed_settings.get("내레이션", 1.0), 0.1, format="%.1fx")
        
        # 캐릭터 조절
        for i, char in enumerate(used_chars):
            with cols[i+1]:
                st.session_state.speed_settings[char] = st.slider(f"🎭 {char}", 0.7, 1.5, st.session_state.speed_settings.get(char, 1.0), 0.1, format="%.1fx")

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
                    
                    # 결과를 담을 컬럼들
                    cols_pre = st.columns(len(sample_chars))
                    
                    found_any = False
                    for idx, char in enumerate(sample_chars):
                        voice_id = st.session_state.get('all_narration_voice_id') if char == "내레이션" else st.session_state.character_voice_mappings.get(char)
                        
                        if voice_id:
                            # 해당 캐릭터의 첫 번째 대사 찾기 (현재 뷰 기준)
                            char_line = next((item['text'] for item in st.session_state.parsed_data_dict[current_view_diff] if item['character'] == char), "설정된 대사가 없습니다.")
                            
                            found_any = True
                            sample_audio = audio_engine.generate_audio(st.session_state.api_key, char_line, voice_id)
                            
                            if isinstance(sample_audio, bytes):
                                target_speed = st.session_state.speed_settings.get(char, 1.0)
                                final_sample = audio_engine.apply_speed_control(sample_audio, target_speed)
                                with cols_pre[idx]:
                                    st.write(f"**{char}** ({target_speed}x)")
                                    st.caption(f"\"{char_line[:30]}...\"" if len(char_line) > 30 else f"\"{char_line}\"")
                                    st.audio(final_sample, format="audio/mpeg")
                            else:
                                with cols_pre[idx]:
                                    st.error(f"{char} 생성 실패")
                    
                    if not found_any:
                        st.warning("보이스가 지정된 캐릭터가 없습니다. Step 2에서 보이스를 먼저 설정해 주세요.")
                    else:
                        st.success("실제 대사 기반 샘플 생성 완료!")

    st.info("💡 팁: 캐릭터의 성격(톤)에 맞춰 목소리의 감정 표현이 자동으로 미세 조정됩니다.")
    
    if st.button("✨ 모든 난이도 음원 일괄 생성", use_container_width=True):
        if not st.session_state.api_key:
            st.error("API Key가 필요합니다.")
        else:
            # 분석 완료된 모든 난이도에 대해 루프 실행
            target_diffs = [d for d in DIFFICULTIES if st.session_state.script_parsed_dict[d]]
            
            if not target_diffs:
                st.warning("분석 완료된 대본이 없습니다.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total_target_lines = sum(len(set(f"{item['scene']}_{item['line']}" for item in st.session_state.parsed_data_dict[d])) for d in target_diffs)
                processed_lines_total = 0
                
                for d_idx, d in enumerate(target_diffs):
                    status_text.text(f"[{d}] 난이도 음원 생성 중...")
                    
                    # 문장(Line) 단위로 그룹화
                    lines_to_process = {}
                    for item in st.session_state.parsed_data_dict[d]:
                        line_key = f"{item['scene']}_{item['line']}"
                        if line_key not in lines_to_process:
                            lines_to_process[line_key] = []
                        lines_to_process[line_key].append(item)
                    
                    for line_key, segments in lines_to_process.items():
                        segment_audios = []
                        for seg in segments:
                            voice_id = st.session_state.voice_mappings_dict[d].get(seg['segment_id'])
                            
                            if voice_id:
                                seg_mood = seg.get('mood', 'Neutral')
                                preset = MOOD_PRESETS.get(seg_mood, MOOD_PRESETS['Neutral'])
                                
                                audio_bytes = audio_engine.generate_audio(
                                    st.session_state.api_key, 
                                    seg['text'], 
                                    voice_id,
                                    stability=preset['stability'],
                                    similarity_boost=preset['similarity_boost'],
                                    style=preset['style']
                                )
                                
                                if isinstance(audio_bytes, bytes):
                                    char_name = seg.get('character', '내레이션')
                                    current_speed = st.session_state.speed_settings.get(char_name, 1.0)
                                    if current_speed != 1.0:
                                        audio_bytes = audio_engine.apply_speed_control(audio_bytes, current_speed)
                                    segment_audios.append(audio_bytes)
                        
                        if segment_audios:
                            merged_audio = audio_engine.merge_audio(segment_audios)
                            st.session_state.audio_cache_dict[d][line_key] = merged_audio
                        
                        processed_lines_total += 1
                        progress_bar.progress(processed_lines_total / total_target_lines)
                
                status_text.text("모든 난이도 음원 생성 및 병합 완료!")
                st.balloons()

    # 오디오 플레이어 시각화 (현재 뷰어 난이도 기준)
    if st.session_state.audio_cache_dict[current_view_diff]:
        current_scene = None
        
        # 문장 단위 표시를 위해 다시 그룹화
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
                    cols = st.columns([1.5, 5.5, 2, 2])
                    cols[0].write(f"**ID: {segs[0]['line']}**")
                    
                    # 미리보기 텍스트 구성 (대사는 따옴표 포함)
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
                    
                    if cols[3].button("🔄 다시 생성", key=f"regen_{line_key}"):
                        st.info("개별 문장 재생성 기능은 현재 개발 중입니다. 전체 생성을 이용해 주세요.")

        # 4. 다운로드 섹션
        st.divider()
        st.header("4. 결과물 전체 다운로드")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # 개별 파일 다운로드 (현재 뷰 난이도 기준)
            zip_data = exporter.create_individual_zip(difficulty_suffix, st.session_state.parsed_data_dict[current_view_diff], st.session_state.audio_cache_dict[current_view_diff])
            if zip_data:
                st.download_button(
                    label=f"📦 {current_view_diff} 개별 파일 다운로드 (ZIP)",
                    data=zip_data,
                    file_name=f"{difficulty_suffix}_individual_files.zip",
                    mime="application/octet-stream",
                    use_container_width=True,
                    key=f"btn_download_individual_{current_view_diff}"
                )
        
        with col2:
            # 씬별 병합 다운로드 (현재 뷰 난이도 기준)
            scene_groups = {}
            added_line_keys = set()
            for item in st.session_state.parsed_data_dict[current_view_diff]:
                scene = item['scene']
                line_key = f"{scene}_{item['line']}"
                if line_key in added_line_keys: continue
                if scene not in scene_groups: scene_groups[scene] = []
                if line_key in st.session_state.audio_cache_dict[current_view_diff]:
                    scene_groups[scene].append(st.session_state.audio_cache_dict[current_view_diff][line_key])
                    added_line_keys.add(line_key)
            
            if scene_groups:
                merged_cache = {s: audio_engine.merge_audio(al) for s, al in scene_groups.items() if al}
                first_book_id = st.session_state.parsed_data_dict[current_view_diff][0].get('book_id', '') if st.session_state.parsed_data_dict[current_view_diff] else ""
                zip_data_merged = exporter.create_merged_zip(difficulty_suffix, merged_cache, book_id=first_book_id)
                
                st.download_button(
                    label=f"🎞️ {current_view_diff} 씬별 병합 다운로드 (ZIP)",
                    data=zip_data_merged,
                    file_name=f"{difficulty_suffix}_merged_scenes.zip",
                    mime="application/octet-stream",
                    use_container_width=True,
                    key=f"btn_download_merged_{current_view_diff}"
                )
