import re
import pandas as pd
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

def parse_dataframe(df, confirmed_characters_list=None):
    """
    구조화된 시트(CSV/Excel)의 각 행을 처리합니다.
    """
    parsed_data = []
    global_last_speaker = "캐릭터"
    
    # 발화 동사 목록 확장
    verbs_regex = r'(?:says|said|asked|exclaimed|shouted|shouts|replied|cried|whispered|whispers|thought|added|lied|commanded|cheered|ordered|begged|groaned|sighed|told|sent|answered)'
    
    accumulated_text = ""

    for idx, row in df.iterrows():
        row_id = str(row.get('ID', f"ROW{idx}"))
        row_key = str(row.get('Key', f"KEY{idx}"))
        text = str(row.get('Text', ''))
        
        if not text.strip():
            continue
            
        text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
        text = text.replace('—', '-').replace('–', '-')

        accumulated_text += " " + text
        
        # 여기서 통문장 text 하나에 대해 대사/내레이션 분리 (기존 로직 유지)
        segments = re.split(r'("[^"\n]*"|\'[^\'\n]*\')', text)
        temp_segs = []
        line_speaker = None
        
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
                
                # 규칙 1: 직접 매칭
                speaker_match = re.search(rf'\b{verbs_regex}\b\s+{noun_phrase}|{noun_phrase}\s+\b{verbs_regex}\b', narration, re.IGNORECASE)
                
                if speaker_match:
                    found = next((g for g in speaker_match.groups() if g is not None), None)
                    if found: line_speaker = found
                
                # 규칙 2: 대명사 해결 -> 위에서 못 찾았을 때만
                if not line_speaker:
                    pronoun_match = re.search(rf'\b(he|she|they|it)\b\s+{verbs_regex}|{verbs_regex}\s+\b(he|she|they|it)\b', narration, re.IGNORECASE)
                    if pronoun_match:
                        pronoun = pronoun_match.group(1) or pronoun_match.group(2)
                        text_up_to_here = accumulated_text[:accumulated_text.find(narration)]
                        resolved = resolve_pronoun(pronoun, text_up_to_here, confirmed_characters_list)
                        if resolved: line_speaker = resolved

                temp_segs.append({'type': '내레이션', 'text': narration})

        # 규칙 3: 상태 유지
        final_speaker = line_speaker or global_last_speaker
        global_last_speaker = final_speaker
        
        for seg_idx, seg in enumerate(temp_segs):
            char_label = final_speaker if seg['type'] == '대사' else '내레이션'
            parsed_data.append({
                'ID': row_id,
                'Key': row_key,
                'seg_idx': seg_idx,
                'segment_id': f"{row_key}_{seg_idx}",
                'type': seg['type'],
                'character': char_label,
                'text': seg['text'],
                'scene': row_key, # app.py 표시 용 (Key)
                'line': row_id    # app.py 표시 용 (ID)
            })
                    
    return parsed_data, df

def extract_characters(parsed_data, confirmed_characters_list=None):
    """
    이제 Gemini를 통해 사전에 확장된 캐릭터 리스트가 들어오게 됩니다.
    이 함수는 호환성을 위해 유지하며, 주입받은 캐릭터 리스트 딕셔너리를 그대로 반환합니다.
    """
    if confirmed_characters_list:
        return confirmed_characters_list
    return {}
