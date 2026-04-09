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

def parse_dataframe(df, confirmed_characters_list=None, ai_metadata=None):
    """
    구조화된 시트(CSV/Excel)의 각 행을 처리합니다.
    ai_metadata: Gemini가 분석한 [{"text": "...", "speaker": "...", "mood": "..."}] 리스트
    """
    parsed_data = []
    global_last_speaker = "캐릭터"
    
    # 발화 동사 목록 확장
    verbs_regex = r'(?:says|said|asked|exclaimed|shouted|shouts|replied|cried|whispered|whispers|thought|added|lied|commanded|cheered|ordered|begged|groaned|sighed|told|sent|answered)'
    
    accumulated_text = ""

    # AI 메타데이터를 텍스트 기반으로 검색하기 위한 딕셔너리 구성 (정밀도 향상)
    ai_lookup = {}
    if ai_metadata and isinstance(ai_metadata, list):
        for item in ai_metadata:
            if isinstance(item, dict) and 'text' in item:
                ai_lookup[str(item['text']).strip()] = item

    for idx, row in df.iterrows():
        row_id = str(row.get('ID', f"ROW{idx}"))
        row_key = str(row.get('Key', f"KEY{idx}"))
        text = str(row.get('Text', ''))
        
        if not text.strip(): continue
        text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
        # 세그먼트 분리 (따옴표 기준)
        # 어포스트로피(Milo's, don't 등)는 살리고, 대사 목적의 따옴표만 분리하도록 정규식 개선
        # (?<!\w)'|'(?!\w) 패턴을 고려하여 단어 중간의 '는 무시
        segments = re.finditer(r'("[^"\n]*"|(?<!\w)\'[^\'\n]*\'(?!\w)|(?:[^\'"]|(?<=\w)\'(?=\w))+)', text)
        temp_segs = []
        
        for match in segments:
            seg = match.group(0)
            if not seg or not seg.strip(): continue
            
            is_dialogue = (seg.startswith('"') and seg.endswith('"')) or (seg.startswith("'") and seg.endswith("'"))
            # 어포스트로피 예외 처리: 만약 따옴표로 시작하더라도 내부에 공백이 없고 매우 짧으면(예: 's) 내레이션으로 간주
            if is_dialogue and len(seg) <= 3 and "'" in seg:
                is_dialogue = False
            
            seg_text = seg[1:-1].strip() if is_dialogue else seg.strip()
            if not seg_text: continue

            # AI 메타데이터 우선 검색 (텍스트 조각이 AI 분석 문장의 일부인지 확인)
            ai_item = ai_lookup.get(seg_text)
            if not ai_item:
                # 더 유연한 검색: 분리된 조각이 AI 분석 결과의 텍스트에 포함되어 있거나 그 반대인 경우
                ai_item = next((v for k, v in ai_lookup.items() if (seg_text in k or k in seg_text)), None)
            
            speaker = None
            mood = 'Neutral'
            if ai_item:
                speaker = ai_item.get('speaker', None)
                if isinstance(speaker, dict): speaker = speaker.get('name', str(speaker))
                if speaker: speaker = str(speaker).strip()
                
                mood = ai_item.get('mood', 'Neutral')
                if isinstance(mood, dict): mood = mood.get('type', 'Neutral')
                mood = str(mood).strip()
            
            if not speaker and is_dialogue:
                # 대사인데 화자를 못 찾은 경우 Fallback: Regex 기반 추출
                if confirmed_characters_list:
                    char_regex = r'(' + '|'.join(re.escape(c) for c in confirmed_characters_list.keys()) + r')'
                    np = rf'(?:(?:the|a|an|his|her|their)\s+)?{char_regex}'
                else:
                    np = r'(?:(?:the|a|an|his|her|their)\s+)?([A-Z][a-z]+)'
                
                # 원본 row's text에서 동사-화자 패턴 검색
                pattern_match = re.search(rf'\b{verbs_regex}\b\s+{np}|{np}\s+\b{verbs_regex}\b', text, re.IGNORECASE)
                speaker = next((g for g in pattern_match.groups() if g is not None), None) if pattern_match else None

            temp_segs.append({
                'type': '대사' if is_dialogue else '내레이션', 
                'text': seg_text,
                'speaker': speaker,
                'mood': mood
            })

        # Key 파싱 및 ID 구성
        key_parts = [p.strip() for p in row_key.split('_') if p.strip()]
        sc_candidates = [p for p in key_parts if p.upper().startswith("SC")]
        st_candidates = [p for p in key_parts if p.upper().startswith("ST")]
        type_candidates = [p for p in key_parts if p.upper() in ["N", "E", "D"]]
        
        identified = set(sc_candidates + st_candidates + type_candidates)
        remaining = [p for p in key_parts if p not in identified]
        
        scene_num = sc_candidates[0] if sc_candidates else (remaining.pop(0) if remaining else "SC01")
        seq_num = st_candidates[0] if st_candidates else (remaining.pop(0) if remaining else "ST01")
        audio_type = type_candidates[0] if type_candidates else "N"

        for seg_idx, seg in enumerate(temp_segs):
            if seg['type'] == '대사':
                # 대사일 경우 AI가 대사 세그먼트에 명시적으로 지정한 화자 사용, 없으면 직전 화자 상속
                line_speaker = str(seg['speaker'] or global_last_speaker)
                global_last_speaker = line_speaker
                char_label = line_speaker
            else:
                # 내레이션 부분은 무조건 "내레이션"으로 처리
                char_label = "내레이션"
            
            parsed_data.append({
                'ID': row_id, 'Key': row_key, 'book_id': row_id,
                'audio_type': audio_type, 'scene_num': scene_num, 'seq_num': seq_num,
                'seg_idx': seg_idx, 'segment_id': f"{row_key}_{seg_idx}",
                'type': seg['type'], 'character': char_label, 'text': seg['text'], 'mood': seg['mood'],
                'scene': f"{audio_type}_{scene_num}", 'line': seq_num
            })
                    
    return parsed_data, df
                    
    return parsed_data, df

def extract_characters(parsed_data, confirmed_characters_list=None):
    """
    이제 Gemini를 통해 사전에 확장된 캐릭터 리스트가 들어오게 됩니다.
    이 함수는 호환성을 위해 유지하며, 주입받은 캐릭터 리스트 딕셔너리를 그대로 반환합니다.
    """
    if confirmed_characters_list:
        return confirmed_characters_list
    return {}
