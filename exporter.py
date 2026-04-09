import io
import zipfile

def create_individual_zip(difficulty_suffix, parsed_data, audio_cache):
    """
    개별 음성 파일을 ZIP으로 묶어 반환합니다.
    규칙: {BookID}_{scene_num}_{seq_num}_{difficulty_suffix}.mp3 (예: OG0001_SC01_ST01_NA.mp3)
    """
    buffer = io.BytesIO()
    added_keys = set()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for line in parsed_data:
            key = f"{line['scene']}_{line['line']}"
            if key in audio_cache and key not in added_keys:
                book_id = line.get('book_id', 'Unknown')
                scene_num = line.get('scene_num', 'SC00')
                seq_num = line.get('seq_num', 'ST00')
                filename = f"{book_id}_{scene_num}_{seq_num}_{difficulty_suffix}.mp3"
                zf.writestr(filename, audio_cache[key])
                added_keys.add(key)
    return buffer.getvalue()

def create_merged_zip(difficulty_suffix, merged_audio_cache, book_id=""):
    """
    씬별 병합 파일을 ZIP으로 묶어 반환합니다.
    규칙: {BookID}_{scene_num}_{difficulty_suffix}.mp3 (예: OG0001_SC01_NA.mp3)
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for scene_tag, audio_bytes in merged_audio_cache.items():
            # scene_tag는 N_SC01 형태 -> 여기서 scene_num만 추출 (SC01)
            parts = scene_tag.split('_')
            scene_num = parts[1] if len(parts) >= 2 else scene_tag
            filename = f"{book_id}_{scene_num}_{difficulty_suffix}.mp3"
            zf.writestr(filename, audio_bytes)
    return buffer.getvalue()
