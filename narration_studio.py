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

SPEED_OPTIONS = [0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0,
                 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.35, 1.4, 1.45, 1.5]


def _init_state():
    """나레이션 스튜디오 전용 세션 상태 초기화."""
    if "narr_seg_ids" not in st.session_state:
        st.session_state.narr_seg_ids = [0]
    if "narr_next_id" not in st.session_state:
        st.session_state.narr_next_id = 1
    if "narr_audio_cache" not in st.session_state:
        st.session_state.narr_audio_cache = {}   # {seg_id: bytes}
    if "narr_merged_audio" not in st.session_state:
        st.session_state.narr_merged_audio = None
    if "narr_speaker_voices" not in st.session_state:
        st.session_state.narr_speaker_voices = {}  # {speaker_name: voice_id}
    # design_previews / clone_previews 는 app.py 에서 공유
    if "design_previews" not in st.session_state:
        st.session_state.design_previews = {}
    if "clone_previews" not in st.session_state:
        st.session_state.clone_previews = {}


def _active_speakers(seg_ids: list) -> list[str]:
    """현재 입력된 세그먼트에서 고유 화자 목록을 순서 유지하며 반환합니다."""
    seen = []
    for sid in seg_ids:
        name = st.session_state.get(f"narr_seg_sp_{sid}", "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def render():
    _init_state()

    st.subheader("🎬 나레이션 스튜디오")
    st.caption("문장을 입력하고 화자를 지정하면 자동으로 보이스를 배정할 수 있습니다.")

    if not st.session_state.get("api_key"):
        st.warning("⚠️ ElevenLabs API Key가 설정되지 않았습니다. 사이드바에서 먼저 설정해 주세요.")
        return

    voices = st.session_state.get("voices", {})
    seg_ids = st.session_state.narr_seg_ids
    cached = st.session_state.narr_audio_cache

    # ── 섹션 1: 문장 입력 ──────────────────────────────────────────────────────
    st.markdown("#### 📝 문장 입력")
    st.caption("각 줄에 문장을 입력하고 화자 이름을 직접 적어주세요. 화자 이름이 같으면 같은 목소리를 씁니다.")

    # 컬럼 헤더
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
                st.text_input(
                    "화자",
                    key=f"narr_seg_sp_{sid}",
                    label_visibility="collapsed",
                    placeholder="예: 나레이터, 토끼, 곰",
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

            # 개별 생성 + 오디오 플레이어
            cgen, caudio = st.columns([1, 5])
            with cgen:
                if st.button("▶ 생성", key=f"narr_gen_{sid}", use_container_width=True):
                    _generate_single(sid, seg_ids, cached, voices)

            with caudio:
                if sid in cached:
                    pcol, dlcol = st.columns([4, 1])
                    with pcol:
                        st.audio(cached[sid], format="audio/mp3")
                    with dlcol:
                        sp_label = st.session_state.get(f"narr_seg_sp_{sid}", "segment") or "segment"
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

    # ── 섹션 2: 화자별 보이스 배정 ────────────────────────────────────────────
    speakers = _active_speakers(seg_ids)

    st.markdown("#### 🎙️ 화자별 보이스 배정")
    if not speakers:
        st.info("위 문장 입력에서 화자 이름을 입력하면 자동으로 여기에 나타납니다.")
    else:
        st.caption("감지된 화자마다 목소리를 배정하세요. 배정 즉시 해당 화자의 모든 문장에 적용됩니다.")

        # 새 화자는 빈 voice_id로 초기화
        for sp in speakers:
            if sp not in st.session_state.narr_speaker_voices:
                st.session_state.narr_speaker_voices[sp] = ""

        # 헤더
        vh1, vh2, vh3 = st.columns([2, 4, 2])
        vh1.caption("화자")
        vh2.caption("배정 목소리")
        vh3.caption("사용 문장 수")

        for sp in speakers:
            c_sp, c_voice, c_cnt = st.columns([2, 4, 2])
            c_sp.write(f"**{sp}**")

            with c_voice:
                current_vid = st.session_state.narr_speaker_voices.get(sp, "")
                new_vid = voice_selector_ui(
                    key_label=sp,
                    current_voice_id=current_vid,
                    voices_dict=voices,
                    container_key=f"narr_voice_{sp.replace(' ', '_')}",
                    char_info=None,
                    char_name=sp,
                )
                if new_vid != current_vid:
                    st.session_state.narr_speaker_voices[sp] = new_vid
                    st.rerun()

            seg_count = sum(
                1 for sid in seg_ids
                if st.session_state.get(f"narr_seg_sp_{sid}", "").strip() == sp
                and st.session_state.get(f"narr_seg_text_{sid}", "").strip()
            )
            c_cnt.write(f"{seg_count}개")

    st.divider()

    # ── 섹션 3: 전체 생성 / 합치기 / 초기화 ─────────────────────────────────
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
                    err = _do_generate(sid, cached, voices)
                    if err:
                        errors.append(f"줄 {done}: {err}")
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
            _reset()
            st.rerun()


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _do_generate(sid: int, cached: dict, voices: dict) -> str | None:
    """단일 세그먼트를 생성하고 cached에 저장합니다. 오류 시 오류 문자열을 반환합니다."""
    text = st.session_state.get(f"narr_seg_text_{sid}", "").strip()
    sp_name = st.session_state.get(f"narr_seg_sp_{sid}", "").strip()
    mood = st.session_state.get(f"narr_seg_mood_{sid}", "Neutral")
    speed = st.session_state.get(f"narr_seg_speed_{sid}", 1.0)
    voice_id = st.session_state.narr_speaker_voices.get(sp_name, "")

    if not text:
        return None  # 빈 줄은 건너뜀
    if not sp_name:
        return "화자 이름을 입력하세요."
    if not voice_id:
        return f"화자 '{sp_name}'의 목소리가 배정되지 않았습니다."

    p = MOOD_PRESETS[mood]
    result = audio_engine.generate_audio(
        api_key=st.session_state.api_key,
        text=text,
        voice_id=voice_id,
        stability=p["stability"],
        similarity_boost=p["similarity_boost"],
        style=p["style"],
    )
    if isinstance(result, dict) and "error" in result:
        return result["error"]

    if speed != 1.0:
        result = audio_engine.apply_speed_control(result, speed)
    cached[sid] = result
    return None


def _generate_single(sid: int, seg_ids: list, cached: dict, voices: dict):
    """▶ 생성 버튼 클릭 시 단일 세그먼트를 생성합니다."""
    with st.spinner("생성 중..."):
        err = _do_generate(sid, cached, voices)
    if err:
        st.error(err)
    else:
        st.session_state.narr_merged_audio = None
    st.rerun()


def _reset():
    prefix_list = (
        "narr_seg_text_", "narr_seg_sp_", "narr_seg_mood_", "narr_seg_speed_",
    )
    for key in list(st.session_state.keys()):
        if any(key.startswith(pfx) for pfx in prefix_list):
            del st.session_state[key]
    st.session_state.narr_seg_ids = [0]
    st.session_state.narr_next_id = 1
    st.session_state.narr_audio_cache = {}
    st.session_state.narr_merged_audio = None
    st.session_state.narr_speaker_voices = {}
