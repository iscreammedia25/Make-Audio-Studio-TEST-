import io
import zipfile

def create_individual_zip(difficulty_suffix, parsed_data, audio_cache, difficulty=None, cover_audio=None):
    """
    개별 음성 파일을 ZIP으로 묶어 반환합니다.
    일반: {BookID}_{scene_num}_{seq_num}_{difficulty_suffix}.mp3 (예: OG0001_SC01_ST01_N_A.mp3)
    mBook: {BookID}_Cover_A.mp3 (있을 때) + {BookID}_mBook_{seq_num}_A.mp3
    """
    buffer = io.BytesIO()
    added_keys = set()
    mbook_counter = 1
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        if difficulty == "mBook" and cover_audio:
            book_id = parsed_data[0].get('book_id', 'Unknown') if parsed_data else 'Unknown'
            zf.writestr(f"{book_id}_Cover_A.mp3", cover_audio)
        for line in parsed_data:
            key = f"{line['scene']}_{line['line']}"
            if key in audio_cache and key not in added_keys:
                book_id = line.get('book_id', 'Unknown')
                if difficulty == "mBook":
                    filename = f"{book_id}_mBook_ST{mbook_counter:02d}_A.mp3"
                    mbook_counter += 1
                else:
                    seq_num = line.get('seq_num', 'ST00')
                    scene_num = line.get('scene_num', 'SC00')
                    filename = f"{book_id}_{scene_num}_{seq_num}_{difficulty_suffix}.mp3"
                zf.writestr(filename, audio_cache[key])
                added_keys.add(key)
    return buffer.getvalue()

def create_merged_zip(difficulty_suffix, merged_audio_cache, book_id="", difficulty=None, cover_audio=None):
    """
    씬별 병합 파일을 ZIP으로 묶어 반환합니다.
    일반: {BookID}_{scene_num}_{difficulty_suffix}.mp3 (예: OG0001_SC01_N_A.mp3)
    mBook: {BookID}_Cover_A.mp3 (있을 때) + {BookID}_mBook_A.mp3
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        if difficulty == "mBook" and cover_audio:
            zf.writestr(f"{book_id}_Cover_A.mp3", cover_audio)
        for scene_tag, audio_bytes in merged_audio_cache.items():
            if difficulty == "mBook":
                filename = f"{book_id}_mBook_A.mp3"
            else:
                parts = scene_tag.split('_')
                scene_num = parts[1] if len(parts) >= 2 else scene_tag
                filename = f"{book_id}_{scene_num}_{difficulty_suffix}.mp3"
            zf.writestr(filename, audio_bytes)
    return buffer.getvalue()
