import io
import zipfile

def create_individual_zip(category, story_no, parsed_data, audio_cache):
    """개별 음성 파일을 ZIP으로 묶어 반환합니다."""
    # 규칙: [ID 컬럼 값]_[Key 컬럼 값]_A.mp3
    buffer = io.BytesIO()
    added_keys = set()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for line in parsed_data:
            key = f"{line['scene']}_{line['line']}"
            if key in audio_cache and key not in added_keys:
                # line['line'] == ID, line['scene'] == Key
                filename = f"{line['line']}_{line['scene']}_A.mp3"
                zf.writestr(filename, audio_cache[key])
                added_keys.add(key)
    return buffer.getvalue()

def create_merged_zip(category, story_no, merged_audio_cache):
    """씬별 병합 파일을 ZIP으로 묶어 반환합니다."""
    # 규칙: {category}{story_no}_{scene}_A.mp3 (이대로 유지하거나, 단순히 scene_tag(Key)_A.mp3)
    # merged_audio_cache 키가 scene(Key) 임. ID 정보는 개별 라인마다 다를 수 있으므로 씬 병합의 경우 ID가 여러 개 섞임.
    # 사용자가 '한 행에서 생성된' 것을 병합하라고 했으나, 사용자의 의도로 보아 사실상 개별 행(ST)가 "하나의 MP3"가 되는 것임.
    # app.py의 merged_audio_cache는 scene 기준으로 병합함.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for scene_tag, audio_bytes in merged_audio_cache.items():
            filename = f"{category}{story_no}_{scene_tag}_A.mp3"
            zf.writestr(filename, audio_bytes)
    return buffer.getvalue()
