"""공유 UI 컴포넌트 — app.py 와 narration_studio.py 모두에서 사용됩니다."""
import os
import tempfile

import streamlit as st

import audio_engine
import llm_helper
import moviepy as mp

DIFFICULTIES = ["Normal", "Easy", "Difficult", "mBook"]


@st.dialog("🎙️ 보이스 선택", width="large")
def _voice_dialog_modal(key_label, current_voice_id, container_key, char_info, char_name):
    """보이스 선택 다이얼로그. 선택 결과는 session_state[result_key]에 저장 후 rerun으로 닫힘."""
    result_key = f"_vdlg_result_{container_key}"

    st.write(f"**{key_label} 보이스 설정**")

    active_tab = st.radio(
        "탭",
        ["📚 기존 목록", "✨ AI 신규 생성", "🎙️ 파일 클로닝"],
        key=f"tab_sel_{container_key}",
        horizontal=True,
        label_visibility="collapsed",
    )

    # --- Tab 1: 기존 목록 ---
    if active_tab == "📚 기존 목록":
        # 새로고침 버튼을 먼저 처리해 같은 렌더에서 최신 목록 반영
        if st.button("🔄 보이스 목록 새로고침", key=f"refresh_{container_key}", use_container_width=True):
            with st.spinner("최신 목록을 가져오는 중..."):
                updated = audio_engine.get_voices(st.session_state.api_key)
                if updated:
                    st.session_state.voices = updated
                    st.success("목록 업데이트 완료!")

        # 새로고침 후 변경된 voices를 즉시 반영
        voices_dict = st.session_state.get("voices", {})
        voice_names = list(voices_dict.keys())

        search_query = st.text_input(
            "보이스 검색", key=f"search_{container_key}", placeholder="이름으로 검색..."
        ).lower()
        filtered_voices = [name for name in voice_names if search_query in name.lower()]

        with st.container(height=420):
            none_type = "primary" if current_voice_id == "" else "secondary"
            if st.button("선택 안 함", key=f"none_{container_key}",
                         use_container_width=True, type=none_type):
                st.session_state[result_key] = ""
                st.rerun()

            st.divider()
            st.caption("🔑 Voice ID 직접 입력")
            is_manual = current_voice_id and current_voice_id not in [
                v['id'] for v in voices_dict.values() if isinstance(v, dict)
            ]
            prefill = current_voice_id if is_manual else ""
            manual_id_input = st.text_input(
                "Voice ID", value=prefill, key=f"manual_id_{container_key}",
                placeholder="예: 21m00Tcm4TlvDq8ikWAM", label_visibility="collapsed"
            )
            if st.button("✅ 이 ID로 설정", key=f"manual_confirm_{container_key}",
                         use_container_width=True):
                if manual_id_input.strip():
                    st.session_state[result_key] = manual_id_input.strip()
                    st.rerun()

            st.divider()
            for name in filtered_voices:
                v_data = voices_dict[name]
                if not isinstance(v_data, dict):
                    continue
                v_id = v_data['id']
                v_preview = v_data.get('preview')
                is_selected = (v_id == current_voice_id)
                btn_type = "primary" if is_selected else "secondary"

                col_name, col_play, col_sel = st.columns([5.5, 1.5, 3])
                col_name.write(name)
                if v_preview:
                    if col_play.button("🔊", key=f"p_{container_key}_{v_id}"):
                        st.audio(v_preview, format="audio/mpeg", autoplay=True)
                if col_sel.button(
                    "선택" if not is_selected else "✅",
                    key=f"s_{container_key}_{v_id}",
                    type=btn_type, use_container_width=True
                ):
                    st.session_state[result_key] = v_id
                    st.rerun()

    # --- Tab 2: AI 신규 생성 ---
    elif active_tab == "✨ AI 신규 생성":
        if not st.session_state.api_key:
            st.warning("ElevenLabs API Key를 먼저 설정하세요.")
        else:
            st.caption("스토리 맥락을 반영한 보이스 설명을 작성하고 ElevenLabs로 신규 목소리를 생성합니다.")

            char_lines_for_ai = []
            if char_name:
                for d in DIFFICULTIES:
                    for item in st.session_state.get('parsed_data_dict', {}).get(d, []):
                        if item.get('character') == char_name and item.get('type') == '대사':
                            line_text = item.get('text', '').strip('"').strip("'").strip()
                            if line_text and line_text not in char_lines_for_ai:
                                char_lines_for_ai.append(line_text)
                    if len(char_lines_for_ai) >= 5:
                        break

            desc_key = f"d_desc_area_{container_key}"
            if desc_key not in st.session_state:
                st.session_state[desc_key] = ""

            gemini_available = bool(st.session_state.get('gemini_api_key'))
            if gemini_available:
                if st.button("✨ Gemini로 보이스 설명 자동 생성",
                             key=f"d_gemini_btn_{container_key}", use_container_width=True):
                    with st.spinner("Gemini가 스토리를 분석해 보이스 설명을 작성 중..."):
                        best_model = st.session_state.get('gemini_model', 'models/gemini-1.5-flash')
                        g_res = llm_helper.generate_voice_description(
                            st.session_state.gemini_api_key,
                            char_name or "캐릭터",
                            char_info or {},
                            char_lines=char_lines_for_ai,
                            model_name=best_model
                        )
                        if g_res['success']:
                            st.session_state[desc_key] = g_res['description']
                        else:
                            st.error(f"Gemini 오류: {g_res['error']}")
            else:
                st.info("💡 Gemini API Key를 설정하면 스토리 맥락을 반영한 설명을 자동 생성할 수 있습니다.")

            st.text_area(
                "보이스 설명 (영문)", key=desc_key, height=110,
                placeholder=(
                    "예: A warm, cheerful young girl's voice with a bright and energetic tone, "
                    "full of curiosity and wonder."
                ),
                help="ElevenLabs에 전달되는 보이스 설명입니다. 직접 수정하거나 Gemini로 자동 생성하세요."
            )
            voice_desc_input = st.session_state[desc_key]

            _FALLBACK_TEXT = (
                "Hello! I'm so happy to meet you. "
                "Let's go on an adventure together through the magical forest! "
                "Every day brings a new and wonderful surprise."
            )
            if char_lines_for_ai:
                sample_text = " ".join(char_lines_for_ai)
                if len(sample_text) < 100:
                    sample_text += " " + _FALLBACK_TEXT
            else:
                sample_text = _FALLBACK_TEXT

            if st.button("🎲 샘플 생성 및 재생성",
                         key=f"d_gen_btn_{container_key}",
                         use_container_width=True, type="primary"):
                if len(voice_desc_input.strip()) < 20:
                    st.warning("보이스 설명을 20자 이상 입력해 주세요.")
                else:
                    with st.spinner("ElevenLabs에서 목소리 디자인 중..."):
                        res = audio_engine.generate_voice_design_preview(
                            st.session_state.api_key,
                            gender="female", age="middle_aged", accent="american",
                            text=sample_text,
                            custom_description=voice_desc_input.strip()
                        )
                        if res['success']:
                            st.session_state.design_previews[char_name] = {
                                "samples": res['samples'],
                                "selected_idx": 0,
                                "desc": voice_desc_input.strip()
                            }
                        else:
                            st.error(f"생성 실패: {res['error']}")

            if char_name in st.session_state.get('design_previews', {}):
                preview_data = st.session_state.design_previews[char_name]
                samples = preview_data.get("samples", [])
                selected_idx = preview_data.get("selected_idx", 0)

                st.write(f"🎧 **생성된 샘플 ({len(samples)}개) — 들어보고 가장 나은 걸 선택하세요**")
                for i, sample in enumerate(samples):
                    s_cols = st.columns([0.5, 5, 2])
                    is_selected = (i == selected_idx)
                    s_cols[0].markdown("✅" if is_selected else "　")
                    s_cols[1].audio(sample["audio_bytes"], format="audio/mpeg")
                    btn_label = "선택됨" if is_selected else f"#{i+1} 선택"
                    btn_type = "primary" if is_selected else "secondary"
                    if s_cols[2].button(btn_label, key=f"d_sel_{container_key}_{i}",
                                        type=btn_type, use_container_width=True):
                        st.session_state.design_previews[char_name]["selected_idx"] = i

                st.divider()
                if st.button("✅ 선택한 목소리로 저장 및 확정",
                             key=f"d_save_{container_key}", type="primary",
                             use_container_width=True):
                    chosen = samples[selected_idx]
                    with st.spinner("ElevenLabs 라이브러리에 저장 중..."):
                        saved_desc = preview_data.get('desc', voice_desc_input.strip())
                        save_res = audio_engine.create_voice_from_design(
                            st.session_state.api_key,
                            f"{char_name}_AI",
                            chosen["generated_voice_id"],
                            description=saved_desc
                        )
                        if save_res['success']:
                            st.success("저장 완료!")
                            st.session_state.voices = audio_engine.get_voices(st.session_state.api_key)
                            st.session_state[result_key] = save_res['voice_id']
                            st.rerun()
                        else:
                            st.error(f"저장 실패: {save_res['error']}")

    # --- Tab 3: 파일 클로닝 ---
    elif active_tab == "🎙️ 파일 클로닝":
        if not st.session_state.api_key:
            st.warning("ElevenLabs API Key를 먼저 설정하세요.")
        else:
            st.caption("영상이나 음성 파일을 올려 이 캐릭터의 목소리로 복제합니다.")
            st.info("💡1분 내외 길이의 파일 권장. (최소 5초 이상)")
            c_file = st.file_uploader(
                "파일 업로드 (mp4, mp3, wav)",
                type=['mp4', 'mp3', 'wav'], key=f"c_file_{container_key}"
            )
            if c_file:
                if st.button("🎙️ 목소리 추출 및 미리보기",
                             key=f"c_btn_{container_key}", use_container_width=True):
                    with st.spinner("오디오 정제 중..."):
                        file_ext = os.path.splitext(c_file.name)[1].lower()
                        raw_bytes = c_file.getvalue()
                        if file_ext == '.mp4':
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_mp4:
                                tmp_mp4.write(raw_bytes)
                                tmp_mp4_path = tmp_mp4.name
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_mp3:
                                tmp_mp3_path = tmp_mp3.name
                            video = mp.VideoFileClip(tmp_mp4_path)
                            video.audio.write_audiofile(tmp_mp3_path, logger=None)
                            with open(tmp_mp3_path, "rb") as f:
                                raw_bytes = f.read()
                            video.close()
                            os.unlink(tmp_mp4_path)
                            os.unlink(tmp_mp3_path)

                        iso_res = audio_engine.isolate_audio(st.session_state.api_key, raw_bytes)
                        if iso_res['success']:
                            st.session_state.clone_previews[char_name] = iso_res['audio_bytes']
                        else:
                            st.error(f"정제 실패: {iso_res['error']}")

                if char_name in st.session_state.get('clone_previews', {}):
                    st.write("🎧 **정제된 목소리 미리보기**")
                    st.audio(st.session_state.clone_previews[char_name], format="audio/mpeg")
                    if st.button("✅ 이 목소리로 클로닝 및 확정",
                                 key=f"c_save_{container_key}", type="primary",
                                 use_container_width=True):
                        with st.spinner("클로닝 중..."):
                            res = audio_engine.add_voice(
                                st.session_state.api_key,
                                f"{char_name}_Cloned",
                                st.session_state.clone_previews[char_name]
                            )
                            if res['success']:
                                st.success("클로닝 완료!")
                                st.session_state.voices = audio_engine.get_voices(st.session_state.api_key)
                                st.session_state[result_key] = res['voice_id']
                                st.rerun()
                            else:
                                st.error(f"클로닝 실패: {res['error']}")


def voice_selector_ui(key_label, current_voice_id, voices_dict, container_key,
                      char_info=None, char_name=None):
    """다이얼로그를 사용하는 통합 보이스 셀렉터. 선택 시 새 voice_id를, 변경 없으면 current_voice_id를 반환."""
    result_key = f"_vdlg_result_{container_key}"

    # 다이얼로그에서 선택 결과가 돌아온 경우
    if result_key in st.session_state:
        return st.session_state.pop(result_key)

    current_voice_name = next(
        (name for name, data in voices_dict.items()
         if isinstance(data, dict) and data.get('id') == current_voice_id),
        "선택 안 함"
    )
    if current_voice_id and current_voice_name == "선택 안 함" and current_voice_id != "manual":
        current_voice_name = f"수동 입력 ({current_voice_id})"

    if st.button(f"🎙️ {current_voice_name}", use_container_width=True, key=f"vbtn_{container_key}"):
        _voice_dialog_modal(key_label, current_voice_id, container_key, char_info, char_name)

    return current_voice_id
