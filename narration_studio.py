import re
import time

import streamlit as st

import audio_engine
import llm_helper

MOOD_PRESETS = {
    "Neutral":    {"stability": 0.50, "similarity_boost": 0.75, "style": 0.1},
    "Happy":      {"stability": 0.45, "similarity_boost": 0.80, "style": 0.4},
    "Sad":        {"stability": 0.72, "similarity_boost": 0.75, "style": 0.1},
    "Angry":      {"stability": 0.38, "similarity_boost": 0.85, "style": 0.7},
    "Excited":    {"stability": 0.32, "similarity_boost": 0.88, "style": 0.8},
    "Whispering": {"stability": 0.88, "similarity_boost": 0.65, "style": 0.0},
}

SPEED_OPTIONS = [0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.35, 1.4, 1.45, 1.5]

_NARRATION_NAMES = {"내레이션", "narration", "narrator", "나레이터"}


def _init():
    defaults = {
        "narr_speakers":     [{"name": "나레이터", "voice_id": ""}],
        "narr_seg_ids":      [0],
        "narr_next_id":      1,
        "narr_audio_cache":  {},    # {sid: bytes}
        "narr_merged_audio": None,
        "design_previews":   {},
        "clone_previews":    {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _voice_name(vid: str) -> str:
    if not vid:
        return "(선택 안 함)"
    for name, data in st.session_state.get("voices", {}).items():
        if isinstance(data, dict) and data.get("id") == vid:
            return name
    return "(선택 안 함)"


def render():
    _init()

    st.subheader("🎬 나레이션 스튜디오")
    st.caption(
        "문장별로 입력하고 성우를 배정하세요. "
        "인용문+나레이션 혼합 문장은 🤖 AI 버튼으로 분석하면 "
        "각 성우의 음원이 자동으로 합쳐져 한 음원으로 생성됩니다."
    )

    if not st.session_state.get("api_key"):
        st.warning("⚠️ ElevenLabs API Key가 설정되지 않았습니다. 사이드바에서 먼저 설정해 주세요.")
        return

    voices = st.session_state.get("voices", {})
    voice_options = ["(선택 안 함)"] + [n for n, d in voices.items() if isinstance(d, dict)]

    # ── 섹션 1: 성우 설정 ─────────────────────────────────────────────────────
    with st.expander("👥 성우 설정 — 나레이터 및 캐릭터 보이스 배정", expanded=True):
        st.caption("나레이션에 등장하는 성우를 추가하고 각각에 ElevenLabs 목소리를 배정하세요.")

        speakers = st.session_state.narr_speakers
        hc1, hc2, hc3 = st.columns([2, 4, 0.6])
        hc1.caption("성우 이름")
        hc2.caption("배정 목소리")

        for i, sp in enumerate(speakers):
            c_name, c_voice, c_del = st.columns([2, 4, 0.6])

            with c_name:
                new_name = st.text_input(
                    "성우 이름", value=sp["name"],
                    key=f"narr_sp_name_{i}",
                    placeholder="예: 나레이터, 토끼, 곰",
                    label_visibility="collapsed",
                )
                speakers[i]["name"] = new_name

            with c_voice:
                cur_v = _voice_name(sp["voice_id"])
                idx = voice_options.index(cur_v) if cur_v in voice_options else 0
                sel = st.selectbox(
                    "목소리", voice_options, index=idx,
                    key=f"narr_sp_voice_{i}",
                    label_visibility="collapsed",
                )
                if sel != "(선택 안 함)" and sel in voices and isinstance(voices[sel], dict):
                    speakers[i]["voice_id"] = voices[sel]["id"]
                elif sel == "(선택 안 함)":
                    speakers[i]["voice_id"] = ""

            with c_del:
                if len(speakers) > 1 and st.button("🗑️", key=f"narr_sp_del_{i}", help="성우 삭제"):
                    removed = speakers[i]["name"]
                    fallback = speakers[0]["name"] if i != 0 else speakers[1]["name"]
                    for sid in st.session_state.narr_seg_ids:
                        if st.session_state.get(f"narr_seg_sp_{sid}") == removed:
                            st.session_state[f"narr_seg_sp_{sid}"] = fallback
                    speakers.pop(i)
                    st.rerun()

        if st.button("➕ 성우 추가", key="narr_sp_add"):
            speakers.append({"name": f"캐릭터 {len(speakers)}", "voice_id": ""})
            st.rerun()

    st.divider()

    # ── 섹션 2: 문장 입력 ─────────────────────────────────────────────────────
    st.subheader("📝 문장 입력")

    sp_names = [sp["name"] for sp in st.session_state.narr_speakers]
    seg_ids  = st.session_state.narr_seg_ids
    cached   = st.session_state.narr_audio_cache
    gemini_ok = bool(st.session_state.get("gemini_api_key"))

    gh1, gh2, gh3, gh4, _ = st.columns([5, 2, 2, 2, 0.5])
    gh1.caption("문장")
    gh2.caption("화자")
    gh3.caption("감정")
    gh4.caption("속도")

    for sid in list(seg_ids):
        parts = st.session_state.get(f"narr_seg_parts_{sid}")
        is_mixed = bool(parts and len(parts) > 1)

        with st.container(border=True):
            ct, csp, cmo, cspd, cdel = st.columns([5, 2, 2, 2, 0.5])

            with ct:
                st.text_area(
                    "문장", height=80,
                    key=f"narr_seg_text_{sid}",
                    label_visibility="collapsed",
                    placeholder="나레이션 문장을 입력하세요...",
                )

            with csp:
                if st.session_state.get(f"narr_seg_sp_{sid}") not in sp_names:
                    st.session_state[f"narr_seg_sp_{sid}"] = sp_names[0] if sp_names else ""
                st.selectbox(
                    "화자", sp_names,
                    key=f"narr_seg_sp_{sid}",
                    label_visibility="collapsed",
                    disabled=is_mixed,
                )

            with cmo:
                if st.session_state.get(f"narr_seg_mood_{sid}") not in MOOD_PRESETS:
                    st.session_state[f"narr_seg_mood_{sid}"] = "Neutral"
                st.selectbox(
                    "감정", list(MOOD_PRESETS.keys()),
                    key=f"narr_seg_mood_{sid}",
                    label_visibility="collapsed",
                    disabled=is_mixed,
                )

            with cspd:
                if f"narr_seg_speed_{sid}" not in st.session_state:
                    st.session_state[f"narr_seg_speed_{sid}"] = 1.0
                st.select_slider(
                    "속도", options=SPEED_OPTIONS,
                    key=f"narr_seg_speed_{sid}",
                    label_visibility="collapsed",
                )

            with cdel:
                if st.button("🗑️", key=f"narr_del_{sid}", help="이 줄 삭제"):
                    seg_ids.remove(sid)
                    cached.pop(sid, None)
                    st.session_state.narr_merged_audio = None
                    for k in [f"narr_seg_text_{sid}", f"narr_seg_sp_{sid}",
                               f"narr_seg_mood_{sid}", f"narr_seg_speed_{sid}",
                               f"narr_seg_parts_{sid}"]:
                        st.session_state.pop(k, None)
                    for k in list(st.session_state.keys()):
                        if k.startswith(f"narr_part_sp_{sid}_") or k.startswith(f"narr_part_mood_{sid}_"):
                            del st.session_state[k]
                    st.rerun()

            # 혼합 파트 상세 표시
            if is_mixed:
                st.caption("🤖 AI 분석 결과 — 각 파트에 성우와 감정을 배정하세요")
                for j, part in enumerate(parts):
                    pc1, pc2, pc3, pc4 = st.columns([1.5, 3.5, 2, 2])
                    badge = "🎙️ 나레이션" if part["type"] == "내레이션" else f"💬 {part['speaker']}"
                    pc1.markdown(f"**{badge}**")
                    pc2.caption(part["text"])

                    part_sp_key = f"narr_part_sp_{sid}_{j}"
                    if part_sp_key not in st.session_state:
                        if part["type"] == "내레이션":
                            default_sp = sp_names[0] if sp_names else ""
                        else:
                            matched = next(
                                (s["name"] for s in st.session_state.narr_speakers
                                 if s["name"].lower() == part["speaker"].lower()), ""
                            )
                            default_sp = matched if matched else (sp_names[0] if sp_names else "")
                        st.session_state[part_sp_key] = default_sp
                    with pc3:
                        st.selectbox("성우", sp_names, key=part_sp_key, label_visibility="collapsed")

                    part_mood_key = f"narr_part_mood_{sid}_{j}"
                    if part_mood_key not in st.session_state:
                        st.session_state[part_mood_key] = part.get("mood", "Neutral")
                    with pc4:
                        st.selectbox("감정", list(MOOD_PRESETS.keys()),
                                     key=part_mood_key, label_visibility="collapsed")

                if st.button("🔄 분석 초기화", key=f"narr_clear_parts_{sid}"):
                    st.session_state.pop(f"narr_seg_parts_{sid}", None)
                    st.rerun()

            # 하단: 생성 + AI + 오디오
            cgen, cai, caudio = st.columns([1, 1, 5])

            with cgen:
                if st.button("▶ 생성", key=f"narr_gen_{sid}", use_container_width=True):
                    with st.spinner("생성 중..."):
                        err = _generate_segment(sid)
                    if err:
                        st.error(err)
                    else:
                        st.rerun()

            with cai:
                if gemini_ok:
                    if st.button("🤖 AI", key=f"narr_ai_{sid}",
                                 use_container_width=True, help="AI로 화자 자동 분석"):
                        _analyze_segment(sid)
                else:
                    st.button("🤖 AI", disabled=True, key=f"narr_ai_dis_{sid}",
                              use_container_width=True)

            with caudio:
                if sid in cached:
                    pcol, dlcol = st.columns([4, 1])
                    with pcol:
                        st.audio(cached[sid], format="audio/mp3")
                    with dlcol:
                        st.download_button(
                            "⬇️",
                            data=cached[sid],
                            file_name=f"narr_{sid:03d}.mp3",
                            mime="audio/mp3",
                            key=f"narr_dl_{sid}",
                            help="이 줄 다운로드",
                        )

    if st.button("➕ 줄 추가", key="narr_add_row"):
        new_id = st.session_state.narr_next_id
        st.session_state.narr_seg_ids.append(new_id)
        st.session_state.narr_next_id += 1
        st.rerun()

    st.divider()

    # ── 섹션 3: 전체 생성 / 합치기 / 초기화 ──────────────────────────────────
    c1, c2, c3 = st.columns([2, 2, 1])

    with c1:
        if st.button("✨ 전체 생성", type="primary",
                     use_container_width=True, key="narr_gen_all"):
            segs_to_gen = [
                sid for sid in seg_ids
                if st.session_state.get(f"narr_seg_text_{sid}", "").strip()
            ]
            if not segs_to_gen:
                st.warning("생성할 문장이 없습니다.")
            else:
                errors = []
                prog = st.progress(0)
                total = len(segs_to_gen)
                for done, sid in enumerate(segs_to_gen, 1):
                    err = _generate_segment(sid)
                    if err:
                        errors.append(err)
                    prog.progress(done / total)
                st.session_state.narr_merged_audio = None
                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    st.success("✅ 전체 나레이션 생성 완료!")
                    st.balloons()
                st.rerun()

    with c2:
        gen_sids = [sid for sid in seg_ids if sid in cached]
        if gen_sids:
            if st.button("🔗 전체 합치기", use_container_width=True, key="narr_merge_all"):
                with st.spinner("합치는 중..."):
                    audio_list = [cached[sid] for sid in gen_sids]
                    st.session_state.narr_merged_audio = (
                        audio_engine.merge_audio(audio_list) if len(audio_list) > 1 else audio_list[0]
                    )
                st.rerun()
        else:
            st.button("🔗 전체 합치기", use_container_width=True,
                      disabled=True, key="narr_merge_dis")

        if st.session_state.narr_merged_audio is not None:
            st.download_button(
                "⬇️ 합본 다운로드",
                data=st.session_state.narr_merged_audio,
                file_name="narration_merged.mp3",
                mime="audio/mp3",
                use_container_width=True,
                key="narr_dl_merged",
            )

    with c3:
        if st.button("🔄 초기화", use_container_width=True, key="narr_reset_all",
                     help="모든 문장과 음원을 초기화합니다"):
            _reset()
            st.rerun()


# ── 내부 함수 ─────────────────────────────────────────────────────────────────

def _analyze_segment(sid: int):
    """단일 문장을 Gemini로 분석해 화자 파트로 분리."""
    text = st.session_state.get(f"narr_seg_text_{sid}", "").strip()
    if not text:
        st.warning("문장을 입력하세요.")
        return

    gemini_key = st.session_state.gemini_api_key
    best_model = st.session_state.get("gemini_model", "models/gemini-1.5-flash")

    with st.spinner("AI 분석 중..."):
        result = llm_helper.extract_script_metadata_via_gemini(
            gemini_key, text, model_name=best_model
        )

    if not result["success"]:
        st.error(f"분석 실패: {result.get('error', '알 수 없는 오류')}")
        return

    segments_meta = result.get("segments_metadata") or []
    for seg in segments_meta:
        if isinstance(seg, dict):
            sp = seg.get("speaker", "")
            if isinstance(sp, str) and sp.strip().lower() in _NARRATION_NAMES:
                seg["speaker"] = "내레이션"

    raw_parts = []
    for seg in segments_meta:
        if not isinstance(seg, dict):
            continue
        t = seg.get("text", "").strip()
        if not t:
            continue
        sp = seg.get("speaker", "내레이션")
        seg_type = "내레이션" if sp == "내레이션" else "대사"
        raw_parts.append({
            "type":    seg_type,
            "text":    t,
            "speaker": "내레이션" if seg_type == "내레이션" else sp,
            "mood":    seg.get("mood", "Neutral"),
        })

    # Gemini가 혼합 문장을 분리 안 했을 때 클라이언트 측에서 추가 분리
    parts = _split_mixed_parts(raw_parts)

    # 새 캐릭터가 있으면 성우 목록에 자동 추가
    speakers = st.session_state.narr_speakers
    sp_names = [s["name"] for s in speakers]
    for part in parts:
        if (part["type"] == "대사"
                and part["speaker"].strip().lower() not in _NARRATION_NAMES
                and part["speaker"] not in sp_names):
            speakers.append({"name": part["speaker"], "voice_id": ""})
            sp_names.append(part["speaker"])

    if len(parts) > 1:
        st.session_state[f"narr_seg_parts_{sid}"] = parts
    else:
        # 단일 화자 — selectbox만 업데이트
        st.session_state.pop(f"narr_seg_parts_{sid}", None)
        if parts and parts[0]["type"] == "대사" and parts[0]["speaker"] in sp_names:
            st.session_state[f"narr_seg_sp_{sid}"] = parts[0]["speaker"]

    st.rerun()


def _generate_segment(sid: int):
    """세그먼트 음원 생성. 성공하면 None, 실패하면 에러 문자열 반환."""
    text = st.session_state.get(f"narr_seg_text_{sid}", "").strip()
    if not text:
        return f"줄 {sid}: 문장이 비어 있습니다."

    speakers = st.session_state.narr_speakers
    speed    = st.session_state.get(f"narr_seg_speed_{sid}", 1.0)
    parts    = st.session_state.get(f"narr_seg_parts_{sid}")

    if parts and len(parts) > 1:
        # 혼합 문장: 각 파트 생성 후 병합
        audio_parts = []
        for j, part in enumerate(parts):
            sp_name  = st.session_state.get(f"narr_part_sp_{sid}_{j}", "")
            mood     = st.session_state.get(f"narr_part_mood_{sid}_{j}", part.get("mood", "Neutral"))
            sp_data  = next((s for s in speakers if s["name"] == sp_name), None)
            if not sp_data or not sp_data["voice_id"]:
                return f"줄 {sid} 파트 {j+1} '{sp_name}': 목소리가 배정되지 않았습니다."
            p = MOOD_PRESETS.get(mood, MOOD_PRESETS["Neutral"])
            result = audio_engine.generate_audio(
                api_key=st.session_state.api_key,
                text=part["text"],
                voice_id=sp_data["voice_id"],
                stability=p["stability"],
                similarity_boost=p["similarity_boost"],
                style=p["style"],
            )
            if isinstance(result, dict) and "error" in result:
                return f"줄 {sid} 파트 {j+1}: {result['error']}"
            audio_parts.append(result)
            if j < len(parts) - 1:
                time.sleep(0.3)

        merged = audio_engine.merge_audio(audio_parts) if len(audio_parts) > 1 else audio_parts[0]
    else:
        # 단일 화자
        sp_name = st.session_state.get(f"narr_seg_sp_{sid}", "")
        mood    = st.session_state.get(f"narr_seg_mood_{sid}", "Neutral")
        sp_data = next((s for s in speakers if s["name"] == sp_name), None)
        if not sp_data or not sp_data["voice_id"]:
            return f"줄 {sid} '{sp_name}': 목소리가 배정되지 않았습니다."
        p = MOOD_PRESETS.get(mood, MOOD_PRESETS["Neutral"])
        result = audio_engine.generate_audio(
            api_key=st.session_state.api_key,
            text=text,
            voice_id=sp_data["voice_id"],
            stability=p["stability"],
            similarity_boost=p["similarity_boost"],
            style=p["style"],
        )
        if isinstance(result, dict) and "error" in result:
            return result["error"]
        merged = result

    if speed != 1.0:
        merged = audio_engine.apply_speed_control(merged, speed)
    merged = audio_engine.normalize_audio(merged)
    st.session_state.narr_audio_cache[sid] = merged
    st.session_state.narr_merged_audio = None
    return None


def _split_mixed_parts(parts: list) -> list:
    """Gemini가 혼합 문장을 분리 안 했을 때 따옴표 기준으로 클라이언트 측 추가 분리."""
    result = []
    for part in parts:
        subs = [p.strip() for p in re.split(r'("[^"]*"|\'[^\']*\')', part["text"]) if p.strip()]
        if len(subs) <= 1:
            result.append(part)
            continue
        for sub in subs:
            is_quoted = (
                (sub.startswith('"') and sub.endswith('"')) or
                (sub.startswith("'") and sub.endswith("'"))
            )
            new_part = dict(part)
            new_part["text"] = sub
            if is_quoted:
                new_part["type"] = "대사"
            else:
                new_part["type"] = "내레이션"
                new_part["speaker"] = "내레이션"
            result.append(new_part)
    return result


def _reset():
    prefix_list = (
        "narr_seg_text_", "narr_seg_sp_", "narr_seg_mood_", "narr_seg_speed_",
        "narr_sp_name_", "narr_sp_voice_", "narr_seg_parts_",
        "narr_part_sp_", "narr_part_mood_",
        "narr_gen_", "narr_del_", "narr_dl_", "narr_ai_",
    )
    for key in list(st.session_state.keys()):
        if any(key.startswith(pfx) for pfx in prefix_list):
            del st.session_state[key]
    st.session_state.narr_speakers    = [{"name": "나레이터", "voice_id": ""}]
    st.session_state.narr_seg_ids     = [0]
    st.session_state.narr_next_id     = 1
    st.session_state.narr_audio_cache = {}
    st.session_state.narr_merged_audio = None
