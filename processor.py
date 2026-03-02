import re

def parse_script(text):
    """
    1. [SC01] 태그로 씬 분할
    2. 씬을 마침표/물음표/느낌표 기준으로 문장(Line) 단위로 분할 (따옴표 내부 보호)
    3. 각 문장을 큰따옴표(" ") 또는 작은따옴표(' ') 기준으로 세그먼트(Segment) 분할
    4. 내레이션 세그먼트에서 화자를 추측하여 매칭
    """
    scene_pattern = r'(\[SC\d+\])'
    parts = re.split(scene_pattern, text)
    
    parsed_data = []
    last_speaker = "캐릭터"
    last_named_character = None # 최근 언급된 실제 이름 캐릭터 추적

    for i in range(1, len(parts), 2):
        scene_tag = parts[i].strip('[]')
        scene_content = parts[i+1].strip()
        
        # 1. 문장 단위 분할 로직 (개선됨)
        sentences = []
        pattern = re.compile(r'["\'].*?["\']|[.!?]+(?:\s+|$)')
        start = 0
        for match in pattern.finditer(scene_content):
            if any(c in match.group() for c in '.!?') and not match.group().startswith(('"', "'")):
                sentences.append(scene_content[start:match.end()].strip())
                start = match.end()
        
        remaining = scene_content[start:].strip()
        if remaining:
            sentences.append(remaining)
        if not sentences:
            sentences = [scene_content]

        for s_idx, sentence in enumerate(sentences):
            if not sentence.strip():
                continue
                
            line_id = f"{s_idx + 1:02d}"
            segments_matches = re.finditer(r'["\']([^"\'\n]+)["\']|([^"\'\n]+)', sentence)
            
            line_segments = []
            current_line_speaker = None
            
            # 문장 시작 시점에 최근 언급된 캐릭터 찾기 (문장에 이름이 직접 나올 수도 있음)
            for match in segments_matches:
                dialogue = match.group(1)
                narration = match.group(2)
                
                if dialogue:
                    line_segments.append({
                        'type': '대사',
                        'text': dialogue.strip()
                    })
                elif narration and narration.strip():
                    # 화자 추출 시도
                    # 1. 이름 매칭 (exclaimed Didi, Didi said)
                    # 이름은 대문자로 시작하는 단어만 (He, She 등 대명사 제외 처리 필요)
                    speaker_match = re.search(r'(?:exclaimed|said|asked|shouted|replied|cried|whispered)\s+([A-Z][a-z]+)|([A-Z][a-z]+)\s+(?:exclaimed|said|asked|shouted|replied|cried|whispered)', narration, re.IGNORECASE)
                    
                    # 2. 대명사 매칭 (he said, she exclaimed)
                    pronoun_match = re.search(r'\b(he|she|they|it)\b\s+(?:exclaimed|said|asked|shouted|replied|cried|whispered)|(?:exclaimed|said|asked|shouted|replied|cried|whispered)\s+\b(he|she|they|it)\b', narration, re.IGNORECASE)
                    
                    found_speaker = None
                    if speaker_match:
                        temp_name = speaker_match.group(1) or speaker_match.group(2)
                        # 추출된 이름이 일반적인 대명사가 아닐 경우에만 이름으로 인정
                        if temp_name.lower() not in ['he', 'she', 'they', 'it', 'who', 'the']:
                            found_speaker = temp_name
                            last_named_character = found_speaker 
                    
                    # 이름이 안 찾아졌고 대명사가 있다면 가장 최근 이름으로 대체
                    if not found_speaker and pronoun_match and last_named_character:
                        found_speaker = last_named_character
                    
                    if found_speaker:
                        current_line_speaker = found_speaker
                        last_speaker = found_speaker
                    
                    line_segments.append({
                        'type': '내레이션',
                        'text': narration.strip(),
                        'speaker': '내레이션'
                    })
            
            final_speaker = current_line_speaker or last_speaker
            
            for seg_idx, seg in enumerate(line_segments):
                if seg['type'] == '대사':
                    seg['speaker'] = final_speaker
                
                parsed_data.append({
                    'scene': scene_tag,
                    'line': line_id,
                    'seg_idx': seg_idx,
                    'segment_id': f"{scene_tag}_{line_id}_{seg_idx}",
                    'type': seg['type'],
                    'character': seg['speaker'],
                    'text': seg['text']
                })
                    
    return parsed_data

def extract_characters(parsed_data):
    """
    파싱된 데이터에서 고유 캐릭터 목록을 추출하고 속성 제안
    """
    characters = {}
    for item in parsed_data:
        name = item['character']
        if name == '내레이션':
            continue
            
        if name not in characters:
            gender = "중성"
            age = "성인"
            tone = "보통"
            
            # 단순 이름 기반 휴리스틱
            lower_name = name.lower()
            if any(k in lower_name for k in ["he", "boy", "man", "father", "king", "rabbit"]): # rabbit은 예시
                gender = "남성"
            elif any(k in lower_name for k in ["she", "girl", "woman", "mother", "queen", "didi"]): # Didi 예시
                gender = "여성"
            
            characters[name] = {
                "name": name,
                "gender": gender,
                "age": age,
                "tone": tone
            }
    return characters

if __name__ == "__main__":
    sample = """
    [SC01]
    옛날 옛적에 아주 깊은 산골에 할아버지와 할머니가 살고 있었어요.
    "영감, 오늘 장에 가서 맛있는 것 좀 사오세요."
    "허허, 걱정 마구려. 아주 맛있는 떡을 사오겠소."
    [SC02]
    할아버지는 지팡이를 짚고 산길을 내려갔어요.
    어디선가 호랑이 울음소리가 들렸어요. "어흥!"
    """
    import json
    print(json.dumps(parse_script(sample), indent=2, ensure_ascii=False))
