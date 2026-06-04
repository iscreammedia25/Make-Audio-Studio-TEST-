import re
import time

import pandas as pd
import streamlit as st

import audio_engine
import llm_helper
import processor
from ui_helpers import voice_selector_ui

MOOD_PRESETS = {
    "Neutral":    {"stability": 0.50, "similarity_boost": 0.75, "style": 0.1},
    "Happy":      {"stability": 0.45, "similarity_boost": 0.80, "style": 0.4},
    "Sad":        {"stability": 0.72, "similarity_boost": 0.75, "style": 0.1},
    "Angry":      {"stability": 0.38, "similarity_boost": 0.85, "style": 0.7},
    "Excited":    {"stability": 0.32, "similarity_boost": 0.88, "style": 0.8},
    "Whispering": {"stability": 0.88, "similarity_boost": 0.65, "style": 0.0},
}

_NARRATION_NAMES = {"내레이션", "narration", "narrator"}


def _init():
    defaults = {
        "narr_parsed_data": [],
        "narr_characters": {},
        "narr_voice_mappings": {},       # {segment_id: voice_id}
        "narr_char_voice_mappings": {},  # {char_name: voice_id}
        "narr_narration_voice_id": "",
        "narr_audio_cache": {},          # {segment_id: bytes}
        "narr_merged_audio": None,
        "narr_script_analyzed": False,
        "narr_speed_settings": {"내레이션": 1.0},
        "narr_generation_errors": [],
        "design_previews": {},
        "clone_previews": {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def render():
    _init()

    st.subheader("🎬 나레이션 스튜디오")
    st.caption("텍스트를 입력하면 내레이션과 화자를 자동 인식하고 목소리를 배정합니다.")

    if not st.session_state.get("api_key"):
        st.warning("⚠️ ElevenLabs API Key가 설정되지 않았습니다. 사이드바에서 먼저 설정해 주세요.")
        return

    voices = st.session_state.get("voices", {})

    # ── Step 1: 텍스트 입력 & AI 분석 ──────────────────────────────────────────
    st.markdown("#### Step 1: 텍스트 입력 및 AI 분석")

    st.text_area(
        "스토리 텍스트",
        height=260,
        key="narr_script_input",
        placeholder=(
            "동화 대본이나 스크립트를 붙여넣으세요.\n\n"
            "예)\n"
            "토끼가 숲속을 걷고 있었어요.\n"
            "\"어머, 꽃이 피었네!\" 토끼가 말했어요.\n"
            "곰이 다가왔어요. \"안녕!\" 곰이 인사했어요."
        ),
    )

    c_analyze, c_reset = st.columns([3, 1])
    with c_analyze:
        if st.button("✨ AI 분석하기", type="primary", use_container_width=True, key="narr_analyze_btn"):
            script = st.session_state.get("narr_script_input", "").strip()
            if not script:
                st.warning("텍스트를 입력하세요.")
            elif not st.session_state.get("gemini_api_key"):
                st.error("사이드바에서 Gemini API Key를 먼저 설정하세요.")
            else:
                _analyze(script)

    with c_reset:
        if st.button("🔄 초기화", use_container_width=True, key="narr_reset_btn"):
            _reset()
            st.rerun()

    if not st.session_state.narr_script_analyzed:
        return

    parsed = st.session_state.narr_parsed_data
    characters = st.session_state.narr_characters

    st.divider()

    # ── Step 2: 보이스 설정 ─────────────────────────────────────────────────────
    st.markdown("#### Step 2: 보이스 설정")

    if not voices:
        st.info("사이드바에서 ElevenLabs API Key를 입력하세요.")
    else:
        # 내레이션 보이스
        st.subheader("🎙️ 내레이션 보이스")
        n_col1, n_col2 = st.columns([3, 1])
        with n_col1:
            new_n_id = voice_selector_ui(
                "내레이션",
                st.session_state.narr_narration_voice_id,
                voices,
                "narr_all_narration",
            )
            if new_n_id != st.session_state.narr_narration_voice_id:
                st.session_state.narr_narration_voice_id = new_n_id
                st.rerun()
        with n_col2:
            if st.button("내레이션 일괄 적용", use_container_width=True, key="narr_apply_narration"):
                vid = st.session_state.narr_narration_voice_id
                if vid:
                    for item in parsed:
                        if item["type"] == "내레이션":
                            st.session_state.narr_voice_mappings[item["segment_id"]] = vid
                    st.success("내레이션 보이스 일괄 적용 완료!")
                    st.rerun()

        # 캐릭터 보이스
        if characters:
            st.write("---")
            st.subheader("👥 캐릭터 보이스")

            char_cols = st.columns(min(len(characters), 4))
            for i, (name, info) in enumerate(characters.items()):
                with char_cols[i % 4]:
                    with st.expander(f"👤 {name}", expanded=True):
                        st.caption(
                            f"{info.get('gender','중성')} | "
                            f"{info.get('age','성인')} | "
                            f"{info.get('tone','보통')}"
                        )
                        current_v = st.session_state.narr_char_voice_mappings.get(name, "")
                        chosen_v = voice_selector_ui(
                            "보이스", current_v, voices,
                            f"narr_v_char_{name}",
                            char_info=info, char_name=name,
                        )
                        if chosen_v != current_v:
                            st.session_state.narr_char_voice_mappings[name] = chosen_v
                            for item in parsed:
                                if item.get("character") == name:
                                    st.session_state.narr_voice_mappings[item["segment_id"]] = chosen_v
                            st.rerun()

                        if st.button("적용", key=f"narr_apply_char_{name}", use_container_width=True):
                            if chosen_v:
                                for item in parsed:
                                    if item.get("character") == name:
                                        st.session_state.narr_voice_mappings[item["segment_id"]] = chosen_v
                                st.rerun()

    st.divider()

    # ── Step 3: 세그먼트 확인 & 편집 ───────────────────────────────────────────
    st.markdown("#### Step 3: 세그먼트 확인 및 편집")

    mood_colors = {
        "Neutral": "gray", "Happy": "green", "Sad": "blue",
        "Angry": "red", "Excited": "orange", "Whispering": "purple",
    }

    h1, h2, h3, h4 = st.columns([1.5, 4.5, 3.5, 2])
    h1.caption("타입 / 화자")
    h2.caption("스크립트")
    h3.caption("보이스 설정")
    h4.caption("미리듣기")

    for i, item in enumerate(parsed):
        seg_id = item["segment_id"]
        mood = item.get("mood", "Neutral")
        m_color = mood_colors.get(mood, "gray")

        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([1.5, 4.5, 3.5, 2])

            with c1:
                is_narr = item["type"] == "내레이션"
                color = "gray" if is_narr else "blue"
                st.markdown(
                    f'<span style="color:{color}"><b>{item["type"]}</b></span><br>'
                    f'<small>{item.get("character","")}</small>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<span style="background:{m_color}22;color:{m_color};'
                    f'padding:2px 5px;border-radius:4px;font-size:0.75em;">{mood}</span>',
                    unsafe_allow_html=True,
                )

            with c2:
                new_text = st.text_area(
                    "text", value=item["text"], height=72,
                    label_visibility="collapsed",
                    key=f"narr_text_{seg_id}",
                )
                if new_text != item["text"]:
                    st.session_state.narr_parsed_data[i]["text"] = new_text

            with c3:
                if voices:
                    current_vid = st.session_state.narr_voice_mappings.get(seg_id, "")
                    new_vid = voice_selector_ui(
                        f"{item['type']} {seg_id[:8]}",
                        current_vid, voices,
                        f"narr_row_{seg_id}",
                        char_info=characters.get(item.get("character", "")),
                        char_name=item.get("character"),
                    )
                    if new_vid != current_vid:
                        st.session_state.narr_voice_mappings[seg_id] = new_vid
                        st.rerun()
                else:
                    st.write("API Key 필요")

            with c4:
                if seg_id in st.session_state.narr_audio_cache:
                    st.audio(st.session_state.narr_audio_cache[seg_id], format="audio/mp3")

    st.divider()

    # ── Step 4: 음원 생성 ───────────────────────────────────────────────────────
    st.markdown("#### Step 4: 음원 생성")

    # 속도 설정
    used_chars = sorted({
        item["character"] for item in parsed
        if item["character"].strip().lower() not in _NARRATION_NAMES
    })
    spd_cols = st.columns(min(len(used_chars) + 1, 4))
    with spd_cols[0]:
        narr_spd = st.slider(
            "🎙️ 내레이션", 0.7, 1.5,
            st.session_state.narr_speed_settings.get("내레이션", 1.0),
            0.05, format="%.2fx", key="narr_spd_narration",
        )
        st.session_state.narr_speed_settings["내레이션"] = narr_spd
    for j, char in enumerate(used_chars):
        with spd_cols[(j + 1) % 4]:
            spd = st.slider(
                f"🎭 {char}", 0.7, 1.5,
                st.session_state.narr_speed_settings.get(char, 1.0),
                0.05, format="%.2fx", key=f"narr_spd_{char}",
            )
            st.session_state.narr_speed_settings[char] = spd

    st.write("---")
    gen_col, merge_col = st.columns(2)

    with gen_col:
        n_segs = len(parsed)
        if st.button(f"✨ 음원 생성 ({n_segs}문장)", type="primary",
                     use_container_width=True, key="narr_generate_btn"):
            if not st.session_state.api_key:
                st.error("API Key가 필요합니다.")
            else:
                _generate_all(parsed)

    with merge_col:
        cached_ids = [item["segment_id"] for item in parsed
                      if item["segment_id"] in st.session_state.narr_audio_cache]
        if cached_ids:
            if st.button("🔗 전체 합치기", use_container_width=True, key="narr_merge_btn"):
                with st.spinner("합치는 중..."):
                    al = [st.session_state.narr_audio_cache[k] for k in cached_ids]
                    st.session_state.narr_merged_audio = (
                        audio_engine.merge_audio(al) if len(al) > 1 else al[0]
                    )
                st.rerun()
        else:
            st.button("🔗 전체 합치기", disabled=True,
                      use_container_width=True, key="narr_merge_dis")

        if st.session_state.narr_merged_audio is not None:
            st.download_button(
                "⬇️ 합본 다운로드",
                data=st.session_state.narr_merged_audio,
                file_name="narration_merged.mp3",
                mime="audio/mp3",
                use_container_width=True,
                key="narr_dl_merged",
            )

    if st.session_state.narr_generation_errors:
        st.warning("⚠️ 일부 음원 생성 중 오류가 발생했습니다.")
        for err in st.session_state.narr_generation_errors:
            st.error(err)
        if st.button("오류 메시지 닫기", key="narr_close_errors"):
            st.session_state.narr_generation_errors = []
            st.rerun()


# ── 내부 함수 ──────────────────────────────────────────────────────────────────

def _analyze(script_text: str):
    gemini_key = st.session_state.gemini_api_key
    best_model = st.session_state.get("gemini_model", "models/gemini-1.5-flash")

    with st.spinner("Gemini AI가 텍스트를 분석 중입니다..."):
        result = llm_helper.extract_script_metadata_via_gemini(
            gemini_key, script_text, model_name=best_model
        )

    if not result["success"]:
        st.error(f"분석 실패: {result.get('error', '알 수 없는 오류')}")
        return

    # Gemini가 "Narrator"/"narration" 등 영문으로 반환할 수 있으므로 "내레이션"으로 정규화
    segments_meta = result.get("segments_metadata") or []
    for seg in segments_meta:
        if isinstance(seg, dict):
            sp = seg.get("speaker", "")
            if isinstance(sp, str) and sp.strip().lower() in _NARRATION_NAMES:
                seg["speaker"] = "내레이션"

    if segments_meta:
        # Gemini가 이미 대사/내레이션을 분리한 세그먼트를 반환하므로 직접 사용.
        # parse_dataframe의 fuzzy 텍스트 매칭을 거치면 혼합 문장에서 오인식 발생.
        parsed = []
        for i, seg in enumerate(segments_meta):
            if not isinstance(seg, dict):
                continue
            text = seg.get("text", "").strip()
            if not text:
                continue
            sp = seg.get("speaker", "내레이션")
            seg_type = "내레이션" if sp == "내레이션" else "대사"
            char_label = "내레이션" if seg_type == "내레이션" else sp
            parsed.append({
                "ID": "NARR01", "Key": f"SC01_ST{i+1:03d}",
                "book_id": "NARR01", "audio_type": "N",
                "scene_num": "SC01", "seq_num": f"ST{i+1:03d}",
                "seg_idx": 0, "segment_id": f"SC01_ST{i+1:03d}_0",
                "type": seg_type, "character": char_label,
                "text": text, "mood": seg.get("mood", "Neutral"),
                "scene": "N_SC01", "line": f"ST{i+1:03d}",
            })
        # Gemini가 혼합 문장을 분리 안 했을 때를 대비한 클라이언트 사이드 후처리
        parsed = _split_mixed_segments(parsed)
    else:
        # Gemini 세그먼트 없을 때 fallback
        lines = [ln.strip() for ln in script_text.splitlines() if ln.strip()]
        df = pd.DataFrame({
            "ID": "NARR01",
            "Key": [f"SC01_ST{i+1:03d}" for i in range(len(lines))],
            "Text": lines,
        })
        parsed, _ = processor.parse_dataframe(df, result["characters"])

    all_chars = {
        name: info
        for name, info in result["characters"].items()
        if name.strip().lower() not in _NARRATION_NAMES
    }

    st.session_state.narr_parsed_data = parsed
    st.session_state.narr_characters = all_chars
    st.session_state.narr_voice_mappings = {item["segment_id"]: "" for item in parsed}
    st.session_state.narr_char_voice_mappings = {name: "" for name in all_chars}
    st.session_state.narr_narration_voice_id = ""
    st.session_state.narr_audio_cache = {}
    st.session_state.narr_merged_audio = None
    st.session_state.narr_script_analyzed = True
    st.session_state.narr_generation_errors = []

    n_narr = sum(1 for item in parsed if item["type"] == "내레이션")
    n_dial = len(parsed) - n_narr
    st.success(
        f"✅ 분석 완료! 내레이션 {n_narr}개 · 대사 {n_dial}개 · 캐릭터 {len(all_chars)}명 인식됨."
    )
    st.rerun()


def _generate_all(parsed: list):
    prog = st.progress(0)
    errors = []
    total = len(parsed)

    for i, item in enumerate(parsed):
        seg_id = item["segment_id"]
        char = item.get("character", "내레이션")

        # 보이스 우선순위: 세그먼트별 > 캐릭터별 > 내레이션 전역
        voice_id = st.session_state.narr_voice_mappings.get(seg_id, "")
        if not voice_id:
            if item["type"] == "내레이션" or char.strip().lower() in _NARRATION_NAMES:
                voice_id = st.session_state.narr_narration_voice_id
            else:
                voice_id = st.session_state.narr_char_voice_mappings.get(char, "")

        if not voice_id:
            errors.append(f"[{char}] '{item['text'][:30]}': 보이스 미배정")
            prog.progress((i + 1) / total)
            continue

        preset = MOOD_PRESETS.get(item.get("mood", "Neutral"), MOOD_PRESETS["Neutral"])
        result = audio_engine.generate_audio(
            api_key=st.session_state.api_key,
            text=item["text"],
            voice_id=voice_id,
            stability=preset["stability"],
            similarity_boost=preset["similarity_boost"],
            style=preset["style"],
        )

        if isinstance(result, dict) and "error" in result:
            err_msg = result["error"]
            if "429" in err_msg or "rate" in err_msg.lower():
                errors.append(f"[{char}]: API 요청 한도 초과(429) — 잠시 후 다시 시도하세요.")
            else:
                errors.append(f"[{char}]: {err_msg}")
        else:
            speed = st.session_state.narr_speed_settings.get(
                char, st.session_state.narr_speed_settings.get("내레이션", 1.0)
            )
            if speed != 1.0:
                result = audio_engine.apply_speed_control(result, speed)
            result = audio_engine.normalize_audio(result)
            st.session_state.narr_audio_cache[seg_id] = result

        prog.progress((i + 1) / total)
        time.sleep(0.3)

    st.session_state.narr_merged_audio = None
    st.session_state.narr_generation_errors = errors

    if not errors:
        st.success("✅ 음원 생성 완료!")
        st.balloons()
    st.rerun()


def _split_mixed_segments(parsed: list) -> list:
    """Gemini가 따옴표 대사+나레이션 혼합 문장을 하나의 세그먼트로 반환할 때 클라이언트 측에서 분리."""
    result = []
    for item in parsed:
        text = item["text"]
        # 쌍 따옴표 기준으로 분리 — 구분자(인용문)도 캡처
        parts = [p.strip() for p in re.split(r'("[^"]*"|\'[^\']*\')', text) if p.strip()]
        if len(parts) <= 1:
            result.append(item)
            continue
        for j, part in enumerate(parts):
            is_quoted = (
                (part.startswith('"') and part.endswith('"')) or
                (part.startswith("'") and part.endswith("'"))
            )
            new_item = dict(item)
            new_item["text"] = part
            new_item["segment_id"] = f"{item['segment_id']}s{j}"
            if is_quoted:
                new_item["type"] = "대사"
            else:
                new_item["type"] = "내레이션"
                new_item["character"] = "내레이션"
            result.append(new_item)
    return result


def _reset():
    keys_to_clear = [
        "narr_parsed_data", "narr_characters", "narr_voice_mappings",
        "narr_char_voice_mappings", "narr_narration_voice_id",
        "narr_audio_cache", "narr_merged_audio", "narr_script_analyzed",
        "narr_speed_settings", "narr_generation_errors",
    ]
    for k in keys_to_clear:
        st.session_state.pop(k, None)
    # text_area 위젯 값도 초기화
    st.session_state.pop("narr_script_input", None)
