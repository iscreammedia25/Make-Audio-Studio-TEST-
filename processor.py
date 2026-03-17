import re

def resolve_pronoun(pronoun, text_up_to_here, characters_list):
    blacklist = {
        'and', 'then', 'but', 'so', 'although', 'however', 'therefore', 
        'meanwhile', 'suddenly', 'finally', 'because', 'since', 'while',
        'the', 'this', 'that', 'someone', 'everyone', 'anybody', 'nobody',
        'he', 'she', 'it', 'they', 'we', 'i', 'you', 'one', 'on', 'pop', 'bang',
        'when', 'wow', 'yes', 'no', 'oh', 'ah', 'well', 'too', 'now', 'all', 'soon', 'there',
        'his', 'her', 'their', 'my', 'your', 'our', 'do', 'don\'t', 'did', 'didn\'t'
    }

    # Priority words to match first if they appear nearby
    # AI 추출된 캐릭터들의 이름을 전부 가져와서 성별에 따라 매칭풀에 등록
    he_priorities = [c.lower() for c, data in characters_list.items() if data['gender'] == '남성']
    she_priorities = [c.lower() for c, data in characters_list.items() if data['gender'] == '여성']
    
    # AI가 추출한 모든 문자열 (이름들)
    if characters_list:
        all_names_regex = r'\b(' + '|'.join(re.escape(c) for c in characters_list.keys()) + r')\b'
    else:
        all_names_regex = r'\b([A-Z][a-z]+)\b' # Fallback
        
    matches = list(re.finditer(all_names_regex, text_up_to_here, re.IGNORECASE))
    if not matches: return None
    
    for match in reversed(matches):
        word = match.group(0)
        word_lower = word.lower()
        if word_lower in blacklist: continue
        
        # 성별 기반 우선 순위 매칭
        if pronoun.lower() in ['he', 'his', 'him']:
            if word_lower in he_priorities: return word
        elif pronoun.lower() in ['she', 'her']:
            if word_lower in she_priorities: return word
            
    # 성별 정보가 없거나 일치하는 게 없으면 가장 인접한 캐릭터 반환
    for match in reversed(matches):
        word = match.group(0)
        if word.lower() not in blacklist: return word
                
    return None

def parse_script(text, confirmed_characters_list=None):
    """
    1. #SC01 태그 분할
    2. 스마트 따옴표 정규화
    3. 문장 단위 분할 (따옴표 내부 보호)
    4. 세그먼트 분할 및 화자 매칭 규칙(직접/대명사/상태유지) 적용
    """
    text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
    text = text.replace('—', '-').replace('–', '-')
    
    scene_pattern = r'(#SC\d+)'
    parts = re.split(scene_pattern, text)
    
    parsed_data = []
    global_last_speaker = "캐릭터" # 전체 대본 기준 상태 유지 플래그
    
    # 발화 동사 목록 확장
    verbs_regex = r'(?:says|said|asked|exclaimed|shouted|shouts|replied|cried|whispered|whispers|thought|added|lied|commanded|cheered|ordered|begged|groaned|sighed|told|sent|answered)'
    
    for i in range(1, len(parts), 2):
        scene_tag = parts[i].lstrip('#')
        scene_content = parts[i+1].strip()
        
        # 문장 분리 로직 (따옴표 내 문장부호 보호)
        sentences = []
        pattern = re.compile(r'"[^"]*"|\'[^\']*\'|[.!?]+(?:\s+|$)')
        start = 0
        for match in pattern.finditer(scene_content):
            if any(c in match.group() for c in '.!?') and not match.group().startswith(('"', "'")):
                sentences.append(scene_content[start:match.end()].strip())
                start = match.end()
        if scene_content[start:].strip(): sentences.append(scene_content[start:].strip())

        for s_idx, sentence in enumerate(sentences):
            if not sentence.strip(): continue
            line_id = f"{s_idx + 1:02d}"
            
            # 대사와 내레이터 태그 분리
            segments = re.split(r'("[^"\n]*"|\'[^\'\n]*\')', sentence)
            line_segments = []
            line_speaker = None # 현재 문장에서 발견된 화자
            
            # 1차 패스: 타입 분류 및 현재 문장의 화자 찾기
            temp_segs = []
            for seg in segments:
                if not seg or not seg.strip(): continue
                
                if (seg.startswith('"') and seg.endswith('"')) or (seg.startswith("'") and seg.endswith("'")):
                    # 대사 세그먼트
                    dialogue_text = seg[1:-1].strip()
                    temp_segs.append({'type': '대사', 'text': dialogue_text})
                else:
                    # 내레이션 세그먼트 -> 화자 추출 시도
                    narration = seg.strip()
                    
                    # AI 추출 이름 우선 매칭 정규식
                    if confirmed_characters_list:
                        char_names_regex = r'(' + '|'.join(re.escape(c) for c in confirmed_characters_list.keys()) + r')'
                        noun_phrase = rf'(?:(?:the|a|an|his|her|their)\s+)?{char_names_regex}'
                    else:
                        noun_phrase = rf'(?:(?:the|a|an|his|her|their)\s+)?([A-Z][a-z]+)'
                    
                    # 규칙 1: 직접 매칭 (Milo says)
                    speaker_match = re.search(rf'\b{verbs_regex}\b\s+{noun_phrase}|{noun_phrase}\s+\b{verbs_regex}\b', narration, re.IGNORECASE)
                    
                    if speaker_match:
                        # 캡처된 그룹 중 None이 아닌 첫 번째 값 추출
                        found = next((g for g in speaker_match.groups() if g is not None), None)
                        if found: line_speaker = found
                    
                    # 규칙 2: 대명사 해결 (He said) -> 위에서 화자를 못 찾았을 때만
                    if not line_speaker:
                        pronoun_match = re.search(rf'\b(he|she|they|it)\b\s+{verbs_regex}|{verbs_regex}\s+\b(he|she|they|it)\b', narration, re.IGNORECASE)
                        if pronoun_match:
                            pronoun = pronoun_match.group(1) or pronoun_match.group(2)
                            # 현재 문장까지의 전체 텍스트를 넘겨 역추적
                            text_up_to_here = text[:text.find(sentence) + sentence.find(narration)]
                            resolved = resolve_pronoun(pronoun, text_up_to_here, confirmed_characters_list)
                            if resolved: line_speaker = resolved

                    temp_segs.append({'type': '내레이션', 'text': narration})

            # 2차 패스: 화자 확정 및 저장
            # 규칙 3: 상태 유지 (현재 문장에 화자가 없으면 직전 화자 사용)
            final_speaker = line_speaker or global_last_speaker
            global_last_speaker = final_speaker # 다음 문장으로 상태 전파
            
            for seg_idx, seg in enumerate(temp_segs):
                char_label = final_speaker if seg['type'] == '대사' else '내레이션'
                parsed_data.append({
                    'scene': scene_tag, 'line': line_id, 'seg_idx': seg_idx,
                    'segment_id': f"{scene_tag}_{line_id}_{seg_idx}",
                    'type': seg['type'], 'character': char_label, 'text': seg['text']
                })
                    
    return parsed_data, text
                    
    return parsed_data, text

def extract_characters(parsed_data, confirmed_characters_list=None):
    """
    이제 Gemini를 통해 사전에 확장된 캐릭터 리스트가 들어오게 됩니다.
    이 함수는 호환성을 위해 유지하며, 주입받은 캐릭터 리스트 딕셔너리를 그대로 반환합니다.
    """
    if confirmed_characters_list:
        return confirmed_characters_list
    return {}
