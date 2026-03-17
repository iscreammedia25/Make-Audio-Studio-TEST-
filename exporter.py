import io
import zipfile

def create_individual_zip(category, story_no, parsed_data, audio_cache):
    """개별 음성 파일을 ZIP으로 묶어 반환합니다."""
    # 규칙: {category}{story_no}_{scene}_{line}_A.mp3
    buffer = io.BytesIO()
    added_keys = set()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for line in parsed_data:
            key = f"{line['scene']}_{line['line']}"
            if key in audio_cache and key not in added_keys:
                filename = f"{category}{story_no}_{line['scene']}_{line['line']}_A.mp3"
                zf.writestr(filename, audio_cache[key])
                added_keys.add(key)
    return buffer.getvalue()

def create_merged_zip(category, story_no, merged_audio_cache):
    """씬별 병합 파일을 ZIP으로 묶어 반환합니다."""
    # 규칙: {category}{story_no}_{scene}_A.mp3
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for scene_tag, audio_bytes in merged_audio_cache.items():
            filename = f"{category}{story_no}_{scene_tag}_A.mp3"
            zf.writestr(filename, audio_bytes)
    return buffer.getvalue()
