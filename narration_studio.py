import time

import streamlit as st

import audio_engine
from ui_helpers import voice_selector_ui

MOOD_PRESETS = {
    "Neutral":    {"stability": 0.50, "similarity_boost": 0.75, "style": 0.1},
    "Happy":      {"stability": 0.45, "similarity_boost": 0.80, "style": 0.4},
    "Sad":        {"stability": 0.72, "similarity_boost": 0.75, "style": 0.1},
    "Angry":      {"stability": 0.38, "similarity_boost": 0.85, "style": 0.7},
    "Excited":    {"stability": 0.32, "similarity_boost": 0.88, "style": 0.8},
    "Whispering": {"stability": 0.88, "similarity_boost": 0.65, "style": 0.0},
}

SPEED_OPTIONS = [0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.35, 1.4, 1.45, 1.5]


def _init():
    defaults = {
        "narr_row_ids":      [0],
        "narr_next_row_id":  1,
        "narr_audio_cache":  {},
        "narr_merged_audio": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    for rid in st.session_state.narr_row_ids:
        if f"narr_segs_{rid}" not in st.session_state:
            st.session_state[f"narr_segs_{rid}"] = [0]
        if f"narr_next_seg_{rid}" not in st.session_state:
            st.session_state[f"narr_next_seg_{rid}"] = 1


def render():
    _init()

    st.subheader("🎬 나레이션 스튜디오")
    st.caption(
        "Row = 음원 하나. Row 안에 세그먼트를 여러 개 추가하고 "
        "▶ 생성 버튼 한 번으로 세그먼트들이 합쳐진 음원을 만드세요."
    )

    if not st.session_state.get("api_key"):
        st.warning("⚠️ ElevenLabs API Key가 설정되지 않았습니다. 사이드바에서 먼저 설정해 주세요.")
        return

    row_ids = st.session_state.narr_row_ids
    cached  = st.session_state.narr_audio_cache

    for row_idx, rid in enumerate(list(row_ids)):
        with st.container(border=True):
            hc1, hc2, hc3 = st.columns([5, 1.2, 0.5])
            with hc1:
                st.markdown(f"**Row {row_idx + 1}**")
            with hc2:
                gen_clicked = st.button("▶ 생성", key=f"rgen_{rid}", use_container_width=True)
            with hc3:
                if st.button("🗑️", key=f"rdel_{rid}"):
                    row_ids.remove(rid)
                    cached.pop(rid, None)
                    st.session_state.narr_merged_audio = None
                    _cleanup_row(rid)
                    st.rerun()

            gh1, gh2, gh3, gh4, _ = st.columns([4, 2.5, 2, 2, 0.5])
            gh1.caption("텍스트")
            gh2.caption("보이스")
            gh3.caption("감정")
            gh4.caption("속도")

            for seg_id in list(st.session_state[f"narr_segs_{rid}"]):
                _render_segment(rid, seg_id)

            col_add, _ = st.columns([1.5, 8])
            with col_add:
                if st.button("➕ 세그먼트", key=f"sadd_{rid}", use_container_width=True):
                    nsid = st.session_state[f"narr_next_seg_{rid}"]
                    st.session_state[f"narr_segs_{rid}"].append(nsid)
                    st.session_state[f"narr_next_seg_{rid}"] += 1
                    st.rerun()

            if rid in cached:
                ac1, ac2 = st.columns([5, 1.5])
                with ac1:
                    st.audio(cached[rid], format="audio/mp3")
                with ac2:
                    st.download_button(
                        "⬇️ 다운로드",
                        data=cached[rid],
                        file_name=f"row_{row_idx + 1:03d}.mp3",
                        mime="audio/mp3",
                        key=f"rdl_{rid}",
                        use_container_width=True,
                    )

            if gen_clicked:
                with st.spinner("생성 중..."):
                    err = _generate_row(rid, row_idx + 1)
                if err:
                    st.error(err)
                else:
                    st.rerun()

    if st.button("➕ Row 추가", key="radd"):
        nrid = st.session_state.narr_next_row_id
        st.session_state.narr_row_ids.append(nrid)
        st.session_state.narr_next_row_id += 1
        st.session_state[f"narr_segs_{nrid}"] = [0]
        st.session_state[f"narr_next_seg_{nrid}"] = 1
        st.rerun()

    st.divider()

    c1, c2, c3 = st.columns([2, 2, 1])

    with c1:
        if st.button("✨ 전체 생성", type="primary", use_container_width=True, key="narr_gen_all"):
            if not row_ids:
                st.warning("생성할 Row가 없습니다.")
            else:
                errors = []
                prog = st.progress(0)
                for done, (i, rid) in enumerate(enumerate(row_ids), 1):
                    err = _generate_row(rid, i + 1)
                    if err:
                        errors.append(err)
                    prog.progress(done / len(row_ids))
                st.session_state.narr_merged_audio = None
                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    st.success("✅ 전체 생성 완료!")
                    st.balloons()
                st.rerun()

    with c2:
        gen_rids = [r for r in row_ids if r in cached]
        if gen_rids:
            if st.button("🔗 전체 합치기", use_container_width=True, key="narr_merge"):
                with st.spinner("합치는 중..."):
                    audios = [cached[r] for r in gen_rids]
                    st.session_state.narr_merged_audio = (
                        audio_engine.merge_audio(audios) if len(audios) > 1 else audios[0]
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
        if st.button("🔄 초기화", use_container_width=True, key="narr_reset"):
            _reset()
            st.rerun()


def _render_segment(rid: int, seg_id: int):
    seg_ids = st.session_state[f"narr_segs_{rid}"]
    sc1, sc2, sc3, sc4, sc5 = st.columns([4, 2.5, 2, 2, 0.5])

    with sc1:
        st.text_area(
            "텍스트", height=80,
            key=f"seg_text_{rid}_{seg_id}",
            label_visibility="collapsed",
            placeholder="텍스트 입력...",
        )

    with sc2:
        current_vid = st.session_state.get(f"seg_vid_{rid}_{seg_id}", "")
        voices = st.session_state.get("voices", {})
        new_vid = voice_selector_ui(
            "보이스", current_vid, voices,
            f"narr_{rid}_{seg_id}",
        )
        if new_vid != current_vid:
            st.session_state[f"seg_vid_{rid}_{seg_id}"] = new_vid
            st.rerun()

    with sc3:
        if st.session_state.get(f"seg_mood_{rid}_{seg_id}") not in MOOD_PRESETS:
            st.session_state[f"seg_mood_{rid}_{seg_id}"] = "Neutral"
        st.selectbox(
            "감정", list(MOOD_PRESETS.keys()),
            key=f"seg_mood_{rid}_{seg_id}",
            label_visibility="collapsed",
        )

    with sc4:
        if f"seg_speed_{rid}_{seg_id}" not in st.session_state:
            st.session_state[f"seg_speed_{rid}_{seg_id}"] = 1.0
        st.select_slider(
            "속도", options=SPEED_OPTIONS,
            key=f"seg_speed_{rid}_{seg_id}",
            label_visibility="collapsed",
        )

    with sc5:
        if len(seg_ids) > 1 and st.button("🗑️", key=f"sdel_{rid}_{seg_id}"):
            seg_ids.remove(seg_id)
            _cleanup_seg(rid, seg_id)
            st.rerun()



def _generate_row(rid: int, display_num: int = 0):
    seg_ids = st.session_state.get(f"narr_segs_{rid}", [])
    label   = f"Row {display_num}" if display_num else f"Row {rid}"
    audio_parts = []

    for i, seg_id in enumerate(seg_ids):
        text  = st.session_state.get(f"seg_text_{rid}_{seg_id}", "").strip()
        vid   = st.session_state.get(f"seg_vid_{rid}_{seg_id}", "").strip()
        mood  = st.session_state.get(f"seg_mood_{rid}_{seg_id}", "Neutral")
        speed = st.session_state.get(f"seg_speed_{rid}_{seg_id}", 1.0)

        if not text:
            continue
        if not vid:
            return f"{label} 세그먼트 {i + 1}: 보이스 ID를 입력하세요."

        p = MOOD_PRESETS.get(mood, MOOD_PRESETS["Neutral"])
        result = audio_engine.generate_audio(
            api_key=st.session_state.api_key,
            text=text,
            voice_id=vid,
            stability=p["stability"],
            similarity_boost=p["similarity_boost"],
            style=p["style"],
        )
        if isinstance(result, dict) and "error" in result:
            return f"{label} 세그먼트 {i + 1}: {result['error']}"

        if speed != 1.0:
            result = audio_engine.apply_speed_control(result, speed)
        audio_parts.append(result)

        if i < len(seg_ids) - 1:
            time.sleep(0.3)

    if not audio_parts:
        return f"{label}: 생성할 텍스트가 없습니다."

    merged = audio_engine.merge_audio(audio_parts) if len(audio_parts) > 1 else audio_parts[0]
    merged = audio_engine.normalize_audio(merged)
    st.session_state.narr_audio_cache[rid] = merged
    st.session_state.narr_merged_audio = None
    return None


def _cleanup_row(rid: int):
    for sid in st.session_state.pop(f"narr_segs_{rid}", []):
        _cleanup_seg(rid, sid)
    st.session_state.pop(f"narr_next_seg_{rid}", None)


def _cleanup_seg(rid: int, seg_id: int):
    for suffix in ["text", "vid", "mood", "speed"]:
        st.session_state.pop(f"seg_{suffix}_{rid}_{seg_id}", None)


def _reset():
    prefixes = ("narr_", "seg_", "rgen_", "rdel_", "rdl_", "radd", "sadd_", "sdel_")
    for k in [k for k in st.session_state if any(k.startswith(p) for p in prefixes)]:
        del st.session_state[k]
    st.session_state.narr_row_ids       = [0]
    st.session_state.narr_next_row_id   = 1
    st.session_state.narr_audio_cache   = {}
    st.session_state.narr_merged_audio  = None
    st.session_state["narr_segs_0"]     = [0]
    st.session_state["narr_next_seg_0"] = 1
