import io
import zipfile

def create_individual_zip(difficulty_suffix, parsed_data, audio_cache, difficulty=None):
    """
    개별 음성 파일을 ZIP으로 묶어 반환합니다.
    일반: {BookID}_{scene_num}_{seq_num}_{difficulty_suffix}.mp3 (예: OG0001_SC01_ST01_N_A.mp3)
    mBook: 첫 번째={BookID}_Cover_A.mp3, 이후={BookID}_mBook_{seq_num}_A.mp3
    """
    buffer = io.BytesIO()
    added_keys = set()
    mbook_index = 0
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for line in parsed_data:
            key = f"{line['scene']}_{line['line']}"
            if key in audio_cache and key not in added_keys:
                book_id = line.get('book_id', 'Unknown')
                seq_num = line.get('seq_num', 'ST00')
                if difficulty == "mBook":
                    if mbook_index == 0:
                        filename = f"{book_id}_Cover_A.mp3"
                    else:
                        filename = f"{book_id}_mBook_{seq_num}_A.mp3"
                    mbook_index += 1
                else:
                    scene_num = line.get('scene_num', 'SC00')
                    filename = f"{book_id}_{scene_num}_{seq_num}_{difficulty_suffix}.mp3"
                zf.writestr(filename, audio_cache[key])
                added_keys.add(key)
    return buffer.getvalue()

def create_merged_zip(difficulty_suffix, merged_audio_cache, book_id="", difficulty=None):
    """
    씬별 병합 파일을 ZIP으로 묶어 반환합니다.
    일반: {BookID}_{scene_num}_{difficulty_suffix}.mp3 (예: OG0001_SC01_N_A.mp3)
    mBook: {BookID}_mBook_A.mp3
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for scene_tag, audio_bytes in merged_audio_cache.items():
            if difficulty == "mBook":
                filename = f"{book_id}_mBook_A.mp3"
            else:
                parts = scene_tag.split('_')
                scene_num = parts[1] if len(parts) >= 2 else scene_tag
                filename = f"{book_id}_{scene_num}_{difficulty_suffix}.mp3"
            zf.writestr(filename, audio_bytes)
    return buffer.getvalue()
