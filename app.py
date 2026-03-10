import streamlit as st
import processor
import audio_engine
import exporter
import json
import llm_helper

# 페이지 설정
st.set_page_config(page_title="동화 대본 자동 더빙 에이전트", layout="wide")

# 세션 상태 초기화
if 'api_key' not in st.session_state:
    st.session_state.api_key = ""
if 'gemini_api_key' not in st.session_state:
    st.session_state.gemini_api_key = ""
if 'voices' not in st.session_state:
    st.session_state.voices = {}
if 'parsed_data' not in st.session_state:
    st.session_state.parsed_data = []
if 'voice_mappings' not in st.session_state:
    st.session_state.voice_mappings = {}
if 'audio_cache' not in st.session_state:
    st.session_state.audio_cache = {}
if 'merged_audio_cache' not in st.session_state:
    st.session_state.merged_audio_cache = {}
if 'characters' not in st.session_state:
    st.session_state.characters = {}
if 'character_voice_mappings' not in st.session_state:
    st.session_state.character_voice_mappings = {}
if 'character_confirmed' not in st.session_state:
    st.session_state.character_confirmed = False

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
             st.session_state.gemini_api_key = gemini_key_input.strip()
             st.success("Gemini API Key가 저장되었습니다.")
         else:
             st.warning("Gemini API Key를 입력해 주세요.")

    st.divider()
    category = st.radio("동화 카테고리", ["오리지널(OG)", "클래식(CS)"])
    category_code = "OG" if category == "오리지널(OG)" else "CS"
    story_no = st.text_input("스토리 번호 (예: 0001)", value="0001")

st.title("🎙️ 동화 대본 자동 더빙 및 편집 에이전트")

# 1. 대본 입력 섹션
st.header("1. 대본 입력 및 AI 분석")
script_text = st.text_area("대본을 입력하세요 (예: #SC01 내레이션 \"대사\")", height=200)

if 'script_parsed' not in st.session_state:
    st.session_state.script_parsed = False

if st.button("AI 분석하기 (대본 매칭)"):
    if not script_text:
        st.warning("대본을 입력해 주세요.")
    elif not st.session_state.get('gemini_api_key'):
        st.error("좌측 사이드바에서 Gemini API Key를 입력해 주세요.")
    else:
        with st.spinner("Gemini AI가 대본을 분석하여 캐릭터를 추출하고 있습니다..."):
            # 1단계: Gemini를 통한 캐릭터 추출 (대사 치는 캐릭터만)
            res = llm_helper.extract_characters_via_gemini(st.session_state.gemini_api_key, script_text)
            if not res['success']:
                st.error(res['error'])
            else:
                st.session_state.llm_characters = res['characters']
                st.success("캐릭터 추출 완료! 대본 매칭을 진행합니다...")
                
                # 2단계: 실제 대본 파싱 (확정된 캐릭터 리스트 주입)
                parsed, raw_text = processor.parse_script(script_text, st.session_state.llm_characters)
                if not parsed:
                    st.error("대본 텍스트 구조(#SC01 등)가 잘못되었습니다.")
                else:
                    st.session_state.parsed_data = parsed
                    st.session_state.characters = st.session_state.llm_characters.copy()
                    # 세그먼트 매칭 초기화
                    st.session_state.voice_mappings = {item['segment_id']: "" for item in parsed}
                    st.session_state.character_voice_mappings = {name: "" for name in st.session_state.characters}
                    st.session_state.script_parsed = True
                    st.session_state.character_confirmed = False
                    st.rerun()

# 2. 보이스 설정 (내레이션 + 캐릭터 통합)
if st.session_state.get('script_parsed') and st.session_state.parsed_data:
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
                        for item in st.session_state.parsed_data:
                            if item['type'] == '내레이션':
                                st.session_state.voice_mappings[item['segment_id']] = st.session_state.all_narration_voice_id
                        st.success("내레이션 보이스가 일괄 적용되었습니다.")
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
                            for item in st.session_state.parsed_data:
                                if item.get('character') == new_name:
                                    st.session_state.voice_mappings[item['segment_id']] = chosen_v
                            st.rerun()
                        
                        if st.button("적용", key=f"apply_{new_name}", use_container_width=True):
                            if chosen_v:
                                for item in st.session_state.parsed_data:
                                    if item.get('character') == new_name:
                                        st.session_state.voice_mappings[item['segment_id']] = chosen_v
                                st.rerun()
                    
                    if st.button("삭제", key=f"del_{new_name}", type="secondary", use_container_width=True):
                        st.session_state.characters.pop(new_name)
                        st.session_state.character_voice_mappings.pop(new_name, None)
                        for item in st.session_state.parsed_data:
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
if st.session_state.get('parsed_data') and st.session_state.get('character_confirmed'):
    st.write("---")
    st.header("3. 세그먼트 상세 설정 및 편집")
    h_cols = st.columns([0.6, 1.1, 1.5, 4.3, 3.5, 1.0])
    h_cols[0].markdown("**장면**")
    h_cols[1].markdown("**순서**")
    h_cols[2].markdown("**캐릭터**")
    h_cols[3].markdown("**스크립트 (수정 시 엔터/빈 곳 클릭)**")
    h_cols[4].markdown("**보이스 설정**")
    h_cols[5].markdown("**추가/삭제**")
    st.write("---")

    # 라인별 설정
    for i, item in enumerate(st.session_state.parsed_data):
        key = item['segment_id']
        cols = st.columns([0.6, 1.1, 1.5, 4.3, 3.5, 1.0])
        
        # 1. 장면
        cols[0].write(f"**{item['scene']}**")
        
        # 2. 순서
        with cols[1]:
            # 기본적으로 Line 01부터 Line 10까지 선택지 제공, 그 이상의 라인이 있다면 포함시킴
            line_options = [f"Line {n:02d}" for n in range(1, 11)]
            
            # 파싱된 item['line']이 숫자열 혹은 '03_new' 형태일 수 있음. 'Line ' 접두사를 포함해 통일
            curr_raw_val = str(item['line'])
            curr_display_val = f"Line {curr_raw_val}" if not curr_raw_val.startswith("Line ") else curr_raw_val
            
            # 현재 할당된 라인 번호가 1~10을 벗어난 숫자이거나 02_new 같은 문자열일 경우 선택지에 추가
            if curr_display_val not in line_options:
                line_options.append(curr_display_val)
                line_options.sort() # 파이썬 문자열 기본 정렬(Line 01, Line 02, ...)
                
            selected_line_display = st.selectbox(
                f"Line_{key}", 
                options=line_options, 
                index=line_options.index(curr_display_val), 
                key=f"line_select_{key}", 
                label_visibility="collapsed"
            )
            
            selected_raw_val = selected_line_display.replace("Line ", "")
            if selected_raw_val != curr_raw_val:
                st.session_state.parsed_data[i]['line'] = selected_raw_val
                st.rerun()
                
        # 3. 캐릭터 수동 수정 (드롭다운)
        with cols[2]:
            char_options = list(st.session_state.characters.keys())
            if "내레이션" not in char_options:
                char_options.append("내레이션")
            
            current_char = item['character']
            if current_char not in char_options:
                char_options.insert(0, current_char)
            
            selected_char = st.selectbox(f"Char_{key}", options=char_options, index=char_options.index(current_char), key=f"char_select_{key}", label_visibility="collapsed")
            
            if selected_char != current_char:
                st.session_state.parsed_data[i]['character'] = selected_char
                # 캐릭터가 바뀌면 해당 캐릭터에게 지정된 보이스가 있는지 확인하여 자동 적용
                if selected_char == "내레이션" and st.session_state.get('all_narration_voice_id'):
                    st.session_state.voice_mappings[key] = st.session_state.all_narration_voice_id
                elif selected_char in st.session_state.character_voice_mappings:
                    char_voice = st.session_state.character_voice_mappings[selected_char]
                    if char_voice:
                        st.session_state.voice_mappings[key] = char_voice
                
                # 여기서 extract_characters를 다시 부르면 사용자가 수동으로 수정한 캐릭터 목록이 날아갈 수 있으므로 주의 필요
                # 하지만 드롭다운 옵션 유지를 위해 필요할 수도 있음. 
                # 일단은 characters를 직접 관리하므로 parsed_data 기반 자동 추출은 호출하지 않음.
                st.rerun()

        # 4. 스크립트 수동 수정 (대사의 경우 따옴표 포함)
        with cols[3]:
            is_dialogue = item['type'] == '대사'
            raw_text = item['text']
            display_text = f'"{raw_text}"' if is_dialogue and not (raw_text.startswith(('"', "'")) and raw_text.endswith(('"', "'"))) else raw_text
            
            new_text = st.text_area(f"Text_{key}", value=display_text, key=f"text_input_{key}", label_visibility="collapsed", height=68)
            
            final_save_text = new_text
            if is_dialogue:
                if (final_save_text.startswith('"') and final_save_text.endswith('"')) or \
                   (final_save_text.startswith("'") and final_save_text.endswith("'")):
                    final_save_text = final_save_text[1:-1]
            
            if final_save_text != item['text']:
                st.session_state.parsed_data[i]['text'] = final_save_text
        
        # 5. 보이스 설정
        current_voice_id = st.session_state.voice_mappings.get(key, "")
        with cols[4]:
            if st.session_state.voices:
                chosen_id = voice_selector_ui(f"{item['type']} {key}", current_voice_id, st.session_state.voices, f"row_{key}")
                if chosen_id != current_voice_id:
                    st.session_state.voice_mappings[key] = chosen_id
                    st.rerun()
            else:
                st.write("API Key 필요")
                
            if st.session_state.voice_mappings.get(key) == "manual":
                st.session_state.voice_mappings[key] = st.text_input(f"Voice ID 입력 ({key})", key=f"manual_input_{key}", placeholder="ElevenLabs Voice ID 입력")
        
        # 6. 추가 (+) 버튼
        with cols[5]:
            if st.button("➕", key=f"add_{key}", help="이 대사 아래에 빈 행 추가"):
                import uuid
                new_id = str(uuid.uuid4())[:8]
                new_item = {
                    'scene': item['scene'],
                    'line': f"{item['line']}_new",
                    'type': '대사', # 기본적으로 대사로 세팅
                    'character': item['character'],
                    'text': '',
                    'segment_id': new_id
                }
                st.session_state.parsed_data.insert(i + 1, new_item)
                st.session_state.voice_mappings[new_id] = current_voice_id
                st.rerun()
                
            if st.button("🗑️", key=f"del_row_{key}", help="이 행 삭제"):
                st.session_state.parsed_data.pop(i)
                st.session_state.voice_mappings.pop(key, None)
                st.rerun()

    # 3. 음원 생성 및 미리보기 섹션
    st.divider()
    st.header("3. 음원 생성 및 미리보기")
    
    if st.button("✨ 전체 음원 생성", use_container_width=True):
        if not st.session_state.api_key:
            st.error("API Key가 필요합니다.")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # 문장(Line) 단위로 그룹화하여 세그먼트 생성 및 병합
            lines_to_process = {}
            for item in st.session_state.parsed_data:
                line_key = f"{item['scene']}_{item['line']}"
                if line_key not in lines_to_process:
                    lines_to_process[line_key] = []
                lines_to_process[line_key].append(item)
                
            total_lines = len(lines_to_process)
            for idx, (line_key, segments) in enumerate(lines_to_process.items()):
                status_text.text(f"문장 생성 중: {line_key} ({idx+1}/{total_lines})...")
                
                segment_audios = []
                for seg in segments:
                    voice_id = st.session_state.voice_mappings.get(seg['segment_id'])
                    
                    if voice_id:
                        audio_bytes = audio_engine.generate_audio(st.session_state.api_key, seg['text'], voice_id)
                        if isinstance(audio_bytes, dict) and "error" in audio_bytes:
                            st.error(f"세그먼트 생성 실패 ({seg['segment_id']}): {audio_bytes['error']}")
                        else:
                            segment_audios.append(audio_bytes)
                
                if segment_audios:
                    # 세그먼트들을 하나로 병합하여 라인 캐시에 저장
                    merged_audio = audio_engine.merge_audio(segment_audios)
                    st.session_state.audio_cache[line_key] = merged_audio
                
                progress_bar.progress((idx + 1) / total_lines)
            
            status_text.text("전체 음원 생성 및 병합 완료!")
            st.balloons()

    # 오디오 플레이어 시각화 (문장 단위)
    if st.session_state.audio_cache:
        current_scene = None
        
        # 문장 단위 표시를 위해 다시 그룹화
        lines_mapping = {}
        for item in st.session_state.parsed_data:
            key = f"{item['scene']}_{item['line']}"
            if key not in lines_mapping:
                lines_mapping[key] = []
            lines_mapping[key].append(item)
            
        for line_key, segs in lines_mapping.items():
            scene_tag = segs[0]['scene']
            if scene_tag != current_scene:
                current_scene = scene_tag
                st.subheader(f"🎬 Scene: {current_scene}")
            
            if line_key in st.session_state.audio_cache:
                with st.container(border=True):
                    cols = st.columns([1, 6, 2, 2])
                    cols[0].write(f"**Line {segs[0]['line']}**")
                    
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
                    
                    cols[2].audio(st.session_state.audio_cache[line_key], format="audio/mp3")
                    
                    if cols[3].button("🔄 다시 생성", key=f"regen_{line_key}"):
                        st.info("개별 문장 재생성 기능은 현재 개발 중입니다. 전체 생성을 이용해 주세요.")

        # 4. 다운로드 섹션
        st.divider()
        st.header("4. 결과물 전체 다운로드")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📦 개별 파일 전체 다운로드 (ZIP)", use_container_width=True):
                zip_data = exporter.create_individual_zip(category_code, story_no, st.session_state.parsed_data, st.session_state.audio_cache)
                st.download_button(
                    label="ZIP 다운로드",
                    data=zip_data,
                    file_name=f"{category_code}_{story_no}_individual_files.zip",
                    mime="application/zip",
                    use_container_width=True
                )
        
        with col2:
            if st.button("🎞️ 씬별 병합 파일 다운로드 (ZIP)", use_container_width=True):
                with st.spinner("씬별 병합 중..."):
                    scene_groups = {}
                    added_line_keys = set()
                    for item in st.session_state.parsed_data:
                        scene = item['scene']
                        line_key = f"{scene}_{item['line']}"
                        if line_key in added_line_keys: continue
                        if scene not in scene_groups: scene_groups[scene] = []
                        if line_key in st.session_state.audio_cache:
                            scene_groups[scene].append(st.session_state.audio_cache[line_key])
                            added_line_keys.add(line_key)
                    
                    merged_cache = {s: audio_engine.merge_audio(al) for s, al in scene_groups.items() if al}
                    zip_data_merged = exporter.create_merged_zip(category_code, story_no, merged_cache)
                    st.download_button(
                        label="병합본 ZIP 다운로드",
                        data=zip_data_merged,
                        file_name=f"{category_code}_{story_no}_merged_scenes.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
