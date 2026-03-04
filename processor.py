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
        
        if pronoun.lower() in ['he', 'his', 'him']:
            if word_lower in he_priorities:
                return word
        elif pronoun.lower() in ['she', 'her']:
            if word_lower in she_priorities:
                return word
                
    # Second pass: Look for any available valid character
    for match in reversed(matches):
        word = match.group(0)
        word_lower = word.lower()
        if word_lower in blacklist: continue
        return word
                
    return None


def parse_script(text, confirmed_characters_list=None):
    """
    #SC01 태그로 씬 분할
    씬을 마침표/물음표/느낌표 기준으로 문장(Line) 단위로 분할 (따옴표 내부 보호)
    각 문장을 큰따옴표(" ") 또는 작은따옴표(' ') 기준으로 세그먼트(Segment) 분할
    내레이션 세그먼트에서 화자를 추측하여 매칭
    반환: (parsed_data, original_text)
    """
    scene_pattern = r'(#SC\d+)'
    parts = re.split(scene_pattern, text)
    
    parsed_data = []
    last_speaker = "캐릭터"
    last_named_character = None
    blacklist = {
        'and', 'then', 'but', 'so', 'although', 'however', 'therefore', 
        'meanwhile', 'suddenly', 'finally', 'because', 'since', 'while',
        'the', 'this', 'that', 'someone', 'everyone', 'anybody', 'nobody',
        'he', 'she', 'it', 'they', 'we', 'i', 'you', 'one', 'on', 'pop', 'bang',
        'when', 'wow', 'yes', 'no', 'oh', 'ah', 'well', 'too', 'now', 'all', 'soon', 'there',
        'his', 'her', 'their', 'my', 'your', 'our'
    }

    for i in range(1, len(parts), 2):
        scene_tag = parts[i].lstrip('#')
        scene_content = parts[i+1].strip()
        
        sentences = []
        pattern = re.compile(r'"[^"]*"|\'[^\']*\'|[.!?]+(?:\s+|$)')
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
            # Use re.split to correctly handle apostrophes inside dialogues and preserve them in narration
            # Quotes are used as speech markers, but single quotes can also be apostrophes.
            segments = re.split(r'("[^"\n]*"|\'[^\'\n]*\')', sentence)
            
            line_segments = []
            current_line_speaker = None
            
            for seg in segments:
                if not seg or not seg.strip():
                    continue
                
                if (seg.startswith('"') and seg.endswith('"')) or (seg.startswith("'") and seg.endswith("'")):
                    dialogue = seg[1:-1].strip()
                    # 대사 내부 문장 분리 로직 추가 (. ! ? 뒤에 공백이 오면 분리)
                    # 단, 너무 쪼개지지 않도록 마지막 문장부호는 보존
                    dialogue_sentences = re.split(r'(?<=[.!?])\s+', dialogue)
                    for ds in dialogue_sentences:
                        if ds.strip():
                            line_segments.append({'type': '대사', 'text': ds.strip()})
                else:
                    narration = seg.strip()
                    # Dialogue verbs pattern
                    verbs_regex = r'(?:exclaimed|said|asked|shouted|replied|cried|whispered|sought|added|lied|commanded|cheered|ordered|begged|groaned|sighed|told|sent|answered)'
                    
                    # AI가 추출한 캐릭터 이름들을 우선적으로 매칭
                    if confirmed_characters_list:
                        char_names_regex = r'(' + '|'.join(re.escape(c) for c in confirmed_characters_list.keys()) + r')'
                        noun_phrase = rf'(?:(?:the|a|an|his|her|their)\s+)?{char_names_regex}'
                    else:
                        noun_phrase = rf'(?:(?:the|a|an|his|her|their)\s+)?([A-Z][a-z]+)'
                        
                    speaker_match = re.search(rf'{verbs_regex}\s+{noun_phrase}|{noun_phrase}\s+{verbs_regex}', narration, re.IGNORECASE)
                    
                    # 2. 대명사 인식
                    pronoun_match = re.search(rf'\b(he|she|they|it)\b\s+{verbs_regex}|{verbs_regex}\s+\b(he|she|they|it)\b', narration, re.IGNORECASE)
                    
                    found_speaker = None
                    
                    if pronoun_match:
                        pronoun = pronoun_match.group(1) or pronoun_match.group(2)
                        
                        # Find the first occurrence of the pronoun match within the CURRENT sentence.
                        sentence_idx = sentence.find(pronoun_match.group(0))
                        
                        # Then find where this sentence is located within the entire text
                        # to get the global index.
                        global_sentence_idx = text.find(sentence)
                        
                        if global_sentence_idx != -1 and sentence_idx != -1:
                            idx = global_sentence_idx + sentence_idx
                            text_up_to_here = text[:max(idx, 0)]
                        else:
                            # fallback if find fails
                            text_up_to_here = text
                        
                        resolved = resolve_pronoun(pronoun, text_up_to_here, confirmed_characters_list)
                        if resolved:
                            found_speaker = resolved
                            last_named_character = found_speaker
                        elif last_named_character: # fallback to the VERY last remembered name if lookbehind fails
                            found_speaker = last_named_character
                            
                    elif speaker_match:
                        # Extract the first non-None capturing group which corresponds to the noun
                        groups = speaker_match.groups()
                        temp_name = next((g for g in groups if g is not None), "")
                        
                        if temp_name and temp_name.lower() not in blacklist:
                            found_speaker = temp_name
                            last_named_character = found_speaker
                    
                    if found_speaker:
                        current_line_speaker = found_speaker
                        last_speaker = found_speaker
                    
                    line_segments.append({'type': '내레이션', 'text': narration, 'speaker': '내레이션'})
            
            final_speaker = current_line_speaker or last_speaker
            for seg_idx, seg in enumerate(line_segments):
                if seg['type'] == '대사':
                    seg['speaker'] = final_speaker
                parsed_data.append({
                    'scene': scene_tag, 'line': line_id, 'seg_idx': seg_idx,
                    'segment_id': f"{scene_tag}_{line_id}_{seg_idx}",
                    'type': seg['type'], 'character': seg['speaker'], 'text': seg['text']
                })
                    
    return parsed_data, text

def extract_characters(parsed_data, confirmed_characters_list=None):
    """
    이제 Gemini를 통해 사전에 확장된 캐릭터 리스트가 들어오게 됩니다.
    이 함수는 호환성을 위해 유지하며, 주입받은 캐릭터 리스트 딕셔너리를 그대로 반환합니다.
    """
    if confirmed_characters_list:
        return confirmed_characters_list
    return {}
