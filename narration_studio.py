import streamlit as st
import audio_engine

MOOD_PRESETS = {
    "Neutral":    {"stability": 0.50, "similarity_boost": 0.75, "style": 0.1},
    "Happy":      {"stability": 0.45, "similarity_boost": 0.80, "style": 0.4},
    "Sad":        {"stability": 0.72, "similarity_boost": 0.75, "style": 0.1},
    "Angry":      {"stability": 0.38, "similarity_boost": 0.85, "style": 0.7},
    "Excited":    {"stability": 0.32, "similarity_boost": 0.88, "style": 0.8},
    "Whispering": {"stability": 0.88, "similarity_boost": 0.65, "style": 0.0},
}

SPEED_OPTIONS = [0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0,
                 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.35, 1.4, 1.45, 1.5]


def _voice_name(vid: str) -> str:
    if not vid:
        return "(선택 안 함)"
    for name, data in st.session_state.get("voices", {}).items():
        if isinstance(data, dict) and data.get("id") == vid:
            return name
    return "(선택 안 함)"


def _voice_id(name: str) -> str:
    if name == "(선택 안 함)":
        return ""
    data = st.session_state.get("voices", {}).get(name)
    return data.get("id", "") if isinstance(data, dict) else ""


def render():
    # 세션 상태 초기화
    if "narr_speakers" not in st.session_state:
        st.session_state.narr_speakers = [{"name": "나레이터", "voice_id": ""}]
    if "narr_seg_ids" not in st.session_state:
        st.session_state.narr_seg_ids = [0]
    if "narr_next_id" not in st.session_state:
        st.session_state.narr_next_id = 1
    if "narr_audio_cache" not in st.session_state:
        st.session_state.narr_audio_cache = {}
    if "narr_merged_audio" not in st.session_state:
        st.session_state.narr_merged_audio = None

    st.subheader("🎬 나레이션 스튜디오")
    st.caption("화자별 목소리를 등록하고 문장을 입력하여 나레이션 음원을 생성합니다.")

    if not st.session_state.get("api_key"):
        st.warning("⚠️ ElevenLabs API Key가 설정되지 않았습니다. 사이드바에서 먼저 설정해 주세요.")
        return

    voices = st.session_state.get("voices", {})
    voice_options = ["(선택 안 함)"] + [n for n, d in voices.items() if isinstance(d, dict)]

    # ── 섹션 1: 화자 설정 ────────────────────────────────────────────────────────
    with st.expander("👥 화자 설정 — 등장인물별 목소리 배정", expanded=True):
        st.caption("나레이션에 등장하는 화자를 추가하고 각각에 목소리를 배정하세요.")

        speakers = st.session_state.narr_speakers
        hc1, hc2, hc3 = st.columns([2, 4, 0.6])
        hc1.caption("화자 이름")
        hc2.caption("배정 목소리")

        for i, sp in enumerate(speakers):
            c_name, c_voice, c_del = st.columns([2, 4, 0.6])
            with c_name:
                new_name = st.text_input(
                    "화자 이름", value=sp["name"],
                    key=f"narr_sp_name_{i}",
                    placeholder="예: 나레이터, 토끼, 곰",
                    label_visibility="collapsed",
                )
                speakers[i]["name"] = new_name
            with c_voice:
                cur = _voice_name(sp["voice_id"])
                idx = voice_options.index(cur) if cur in voice_options else 0
                sel = st.selectbox(
                    "목소리", voice_options, index=idx,
                    key=f"narr_sp_voice_{i}",
                    label_visibility="collapsed",
                )
                speakers[i]["voice_id"] = _voice_id(sel)
            with c_del:
                if len(speakers) > 1 and st.button("🗑️", key=f"narr_sp_del_{i}", help="화자 삭제"):
                    deleted_name = speakers[i]["name"]
                    fallback = speakers[0]["name"] if i != 0 else speakers[1]["name"]
                    for sid in st.session_state.narr_seg_ids:
                        if st.session_state.get(f"narr_seg_sp_{sid}") == deleted_name:
                            st.session_state[f"narr_seg_sp_{sid}"] = fallback
                    speakers.pop(i)
                    st.rerun()

        if st.button("➕ 화자 추가", key="narr_add_speaker"):
            speakers.append({"name": f"화자 {len(speakers) + 1}", "voice_id": ""})
            st.rerun()

    st.divider()

    # ── 섹션 2: 문장 입력 ──────────────────────────────────────────────────────
    st.subheader("📝 문장 입력")

    sp_names = [sp["name"] for sp in st.session_state.narr_speakers]
    seg_ids = st.session_state.narr_seg_ids
    cached = st.session_state.narr_audio_cache

    gh1, gh2, gh3, gh4, _ = st.columns([5, 2, 2, 2, 0.5])
    gh1.caption("문장")
    gh2.caption("화자")
    gh3.caption("감정")
    gh4.caption("속도")

    for sid in list(seg_ids):
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
                )
            with cmo:
                if st.session_state.get(f"narr_seg_mood_{sid}") not in MOOD_PRESETS:
                    st.session_state[f"narr_seg_mood_{sid}"] = "Neutral"
                st.selectbox(
                    "감정", list(MOOD_PRESETS.keys()),
                    key=f"narr_seg_mood_{sid}",
                    label_visibility="collapsed",
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
                    st.rerun()

            cgen, caudio = st.columns([1, 5])
            with cgen:
                if st.button("▶ 생성", key=f"narr_gen_{sid}", use_container_width=True):
                    text = st.session_state.get(f"narr_seg_text_{sid}", "").strip()
                    sp_name = st.session_state.get(f"narr_seg_sp_{sid}", sp_names[0] if sp_names else "")
                    sp_data = next(
                        (s for s in st.session_state.narr_speakers if s["name"] == sp_name), None
                    )
                    mood = st.session_state.get(f"narr_seg_mood_{sid}", "Neutral")
                    speed = st.session_state.get(f"narr_seg_speed_{sid}", 1.0)

                    if not text:
                        st.warning("문장을 먼저 입력하세요.")
                    elif not sp_data or not sp_data["voice_id"]:
                        st.error(f"화자 '{sp_name}'의 목소리를 먼저 설정하세요.")
                    else:
                        with st.spinner("생성 중..."):
                            p = MOOD_PRESETS[mood]
                            result = audio_engine.generate_audio(
                                api_key=st.session_state.api_key,
                                text=text,
                                voice_id=sp_data["voice_id"],
                                stability=p["stability"],
                                similarity_boost=p["similarity_boost"],
                                style=p["style"],
                            )
                        if isinstance(result, dict) and "error" in result:
                            st.error(result["error"])
                        else:
                            if speed != 1.0:
                                result = audio_engine.apply_speed_control(result, speed)
                            cached[sid] = result
                            st.session_state.narr_merged_audio = None
                        st.rerun()
            with caudio:
                if sid in cached:
                    pcol, dlcol = st.columns([4, 1])
                    with pcol:
                        st.audio(cached[sid], format="audio/mp3")
                    with dlcol:
                        sp_label = st.session_state.get(f"narr_seg_sp_{sid}", "segment")
                        st.download_button(
                            "⬇️",
                            data=cached[sid],
                            file_name=f"narr_{sid:03d}_{sp_label}.mp3",
                            mime="audio/mp3",
                            key=f"narr_dl_{sid}",
                            help="이 줄만 다운로드",
                        )

    if st.button("➕ 줄 추가", key="narr_add_row"):
        new_id = st.session_state.narr_next_id
        st.session_state.narr_seg_ids.append(new_id)
        st.session_state.narr_next_id += 1
        st.rerun()

    st.divider()

    # ── 섹션 3: 전체 생성 / 합치기 / 초기화 ─────────────────────────────────────
    c1, c2, c3 = st.columns([2, 2, 1])

    with c1:
        if st.button("✨ 전체 생성", type="primary", use_container_width=True, key="narr_gen_all"):
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
                    text = st.session_state.get(f"narr_seg_text_{sid}", "").strip()
                    sp_name = st.session_state.get(f"narr_seg_sp_{sid}", sp_names[0] if sp_names else "")
                    sp_data = next(
                        (s for s in st.session_state.narr_speakers if s["name"] == sp_name), None
                    )
                    mood = st.session_state.get(f"narr_seg_mood_{sid}", "Neutral")
                    speed = st.session_state.get(f"narr_seg_speed_{sid}", 1.0)

                    if not sp_data or not sp_data["voice_id"]:
                        errors.append(f"줄 {done}: 화자 '{sp_name}'의 목소리가 설정되지 않았습니다.")
                        prog.progress(done / total)
                        continue

                    p = MOOD_PRESETS[mood]
                    result = audio_engine.generate_audio(
                        api_key=st.session_state.api_key,
                        text=text,
                        voice_id=sp_data["voice_id"],
                        stability=p["stability"],
                        similarity_boost=p["similarity_boost"],
                        style=p["style"],
                    )
                    if isinstance(result, dict) and "error" in result:
                        errors.append(f"줄 {done}: {result['error']}")
                    else:
                        if speed != 1.0:
                            result = audio_engine.apply_speed_control(result, speed)
                        cached[sid] = result

                    prog.progress(done / total)

                st.session_state.narr_audio_cache = cached
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
            if st.button("🔗 전체 합치기", use_container_width=True, key="narr_merge"):
                with st.spinner("합치는 중..."):
                    audio_list = [cached[sid] for sid in gen_sids]
                    st.session_state.narr_merged_audio = (
                        audio_engine.merge_audio(audio_list) if len(audio_list) > 1 else audio_list[0]
                    )
                st.rerun()
        else:
            st.button("🔗 전체 합치기", use_container_width=True, disabled=True, key="narr_merge_dis")

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
        if st.button("🔄 초기화", use_container_width=True,
                     help="모든 문장과 음원을 초기화합니다", key="narr_reset"):
            prefix_list = (
                "narr_seg_text_", "narr_seg_sp_", "narr_seg_mood_", "narr_seg_speed_",
                "narr_sp_name_", "narr_sp_voice_",
            )
            for key in list(st.session_state.keys()):
                if any(key.startswith(pfx) for pfx in prefix_list):
                    del st.session_state[key]
            st.session_state.narr_speakers = [{"name": "나레이터", "voice_id": ""}]
            st.session_state.narr_seg_ids = [0]
            st.session_state.narr_next_id = 1
            st.session_state.narr_audio_cache = {}
            st.session_state.narr_merged_audio = None
            st.rerun()
