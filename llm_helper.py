from google import genai
import json
import re

def extract_script_metadata_via_gemini(api_key, script_text, model_name='models/gemini-1.5-flash'):
    """
    Gemini API를 사용하여 대본 전체를 분석하고, 캐릭터 목록과 각 대사별 감정(Mood)을 추출합니다.
    """
    if not api_key:
        return {"success": False, "error": "Gemini API 키가 입력되지 않았습니다."}
    
    try:
        client = genai.Client(api_key=api_key)
        safe_script = script_text.replace('\u2014', '-').replace('\u2013', '-')
        
        prompt = f"""
당신은 동화 더빙 전문 에디터입니다. 다음 대본을 분석하여 두 가지 정보를 추출해주세요.

**[중요 지침]**
- **캐릭터 이름은 절대로 번역하지 마세요.** 대본 원문에 적힌 이름(예: Didi, Podo)을 그대로 사용해야 합니다.
- 대명사(he, she)는 문맥을 파악하여 반드시 실제 캐릭터 이름으로 변환하세요.

1. **캐릭터 목록**: 대사를 하는 모든 캐릭터의 정보.
2. **세그먼트 분석**: 대본의 각 행(Row)을 분석하되, 한 행에 **대사(따옴표)와 내레이션이 섞여 있다면 반드시 이를 각각 개별 세그먼트로 분리**하세요.
   - 예: '"Me!" he says.' -> 'Me!' (Speaker: Milo), 'he says.' (Speaker: 내레이션)
   - 예: 'The flower says, "My color helps bees."' -> 'The flower says,' (Speaker: 내레이션), 'My color helps bees.' (Speaker: Flower)
   - Mood 종류: "Neutral", "Happy", "Sad", "Angry", "Excited", "Whispering"

반드시 아래 JSON 형식으로만 응답하세요:
{{
    "characters": [
        {{ "name": "Original Name", "gender": "남성/여성/중성", "age": "아동/청소년/성인/노인", "tone": "차분한/장난기있는 등" }}
    ],
    "segments": [
        {{ "text": "Segment text here", "speaker": "Original Name (or 내레이션)", "mood": "One of the above Moods" }}
    ]
}}

대본 내용:
{safe_script}
"""
        clean_model_id = model_name.replace("models/", "")
        response = client.models.generate_content(
            model=clean_model_id,
            contents=prompt,
        )
        
        result_text = response.text.strip()
        if "```json" in result_text:
            m = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
            if m:
                result_text = m.group(1)
        elif "```" in result_text:
            m = re.search(r'```\s*(.*?)\s*```', result_text, re.DOTALL)
            if m:
                result_text = m.group(1)

        data = json.loads(result_text)

        # UI 친화적인 캐릭터 딕셔너리로 변환 (name 키 없는 항목 방어)
        char_dict = {char['name']: {**char, "description": ""} for char in data.get('characters', []) if char.get('name')}
        
        return {
            "success": True, 
            "characters": char_dict, 
            "segments_metadata": data.get('segments', [])
        }
    except Exception as e:
        return {"success": False, "error": f"Gemini 분석 중 오류: {str(e)}"}


def annotate_segments_via_gemini(api_key, script_text, known_characters, model_name='models/gemini-1.5-flash'):
    """
    이미 알고 있는 캐릭터 목록을 바탕으로 세그먼트 화자/감정만 분석합니다. (병렬 처리용)
    """
    if not api_key:
        return {"success": False, "error": "Gemini API 키가 입력되지 않았습니다."}
    try:
        client = genai.Client(api_key=api_key)
        safe_script = script_text.replace('—', '-').replace('–', '-')
        char_list = ", ".join(known_characters) if known_characters else "없음"

        prompt = f"""당신은 동화 더빙 전문 에디터입니다. 다음 대본의 각 행을 분석하여 화자와 감정을 추출해주세요.

**등장 캐릭터**: {char_list}

**[중요 지침]**
- 캐릭터 이름은 위 목록에 있는 이름을 그대로 사용하세요.
- 대명사(he, she)는 문맥을 파악하여 반드시 실제 캐릭터 이름으로 변환하세요.
- 한 행에 대사(따옴표)와 내레이션이 섞여 있다면 반드시 각각 개별 세그먼트로 분리하세요.
  - 예: '"Me!" he says.' -> 'Me!' (Speaker: Milo), 'he says.' (Speaker: 내레이션)
  - 예: 'The flower says, "My color helps bees."' -> 'The flower says,' (Speaker: 내레이션), 'My color helps bees.' (Speaker: Flower)
- Mood 종류: "Neutral", "Happy", "Sad", "Angry", "Excited", "Whispering"

반드시 아래 JSON 형식으로만 응답하세요:
{{
    "segments": [
        {{ "text": "Segment text here", "speaker": "Character Name (or 내레이션)", "mood": "One of the above Moods" }}
    ]
}}

대본 내용:
{safe_script}
"""
        clean_model_id = model_name.replace("models/", "")
        response = client.models.generate_content(model=clean_model_id, contents=prompt)
        result_text = response.text.strip()
        if "```json" in result_text:
            m = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
            if m:
                result_text = m.group(1)
        elif "```" in result_text:
            m = re.search(r'```\s*(.*?)\s*```', result_text, re.DOTALL)
            if m:
                result_text = m.group(1)
        data = json.loads(result_text)
        return {"success": True, "segments_metadata": data.get('segments', [])}
    except Exception as e:
        return {"success": False, "error": f"Gemini 세그먼트 분석 중 오류: {str(e)}"}


def generate_voice_description(api_key, char_name, char_info, char_lines=None, model_name='models/gemini-1.5-flash'):
    """
    캐릭터 정보와 실제 대사를 바탕으로 ElevenLabs Voice Design에 적합한 영문 설명문을 생성합니다.
    """
    if not api_key:
        return {"success": False, "error": "Gemini API 키가 없습니다."}
    try:
        client = genai.Client(api_key=api_key)

        # 한국어 → 영어 변환 맵
        gender_map = {"남성": "male", "여성": "female", "중성": "neutral"}
        age_map = {"아동": "child (around 6-8 years old)", "청소년": "teenager (around 13-16 years old)",
                   "성인": "adult (in their 30s)", "노인": "elderly (in their 60s-70s)", "아이": "child (around 6-8 years old)"}
        tone_map = {
            "차분한": "calm and composed", "장난기있는": "playful and mischievous",
            "활발한": "energetic and lively", "따뜻한": "warm and nurturing",
            "씩씩한": "brave and bold", "부드러운": "gentle and soft",
            "밝은": "bright and cheerful", "어두운": "somber and serious",
            "신중한": "thoughtful and measured", "엄격한": "stern and authoritative",
            "재미있는": "fun and humorous", "귀여운": "sweet and endearing",
            "용감한": "courageous and strong", "지혜로운": "wise and knowing",
            "명랑한": "cheerful and upbeat", "슬픈": "melancholic and gentle",
            "보통": "natural and conversational",
        }

        g = gender_map.get(char_info.get('gender', ''), 'neutral')
        a = age_map.get(char_info.get('age', ''), 'adult (in their 30s)')
        t_raw = char_info.get('tone', '보통')
        t = tone_map.get(t_raw, t_raw if t_raw.isascii() else 'natural and conversational')
        char_desc = char_info.get('description', '')

        sample_lines = ""
        if char_lines:
            sample_lines = "\n".join(f'  - "{line}"' for line in char_lines[:5])

        prompt = f"""You are an expert voice director writing prompts for ElevenLabs Voice Design AI.
Write a rich, story-specific voice description for a children's audiobook character.

STRICT RULES:
1. Accent MUST be clear American English — never Indian, British, Australian, or any other.
2. Always include "clear American English" in the description.
3. Output ONLY the description — no labels, headers, or explanation.
4. Write exactly 4 sentences, each serving a specific purpose (see structure below).

REQUIRED 4-SENTENCE STRUCTURE:
  Sentence 1 — Character intro + 3 core voice adjectives:
    "Create a [adj], [adj], and [adj] [gender] voice for a children's storybook character named {char_name}."
  Sentence 2 — Voice qualities + real-world or animation character comparison:
    "The voice should sound like [comparison]: [specific technical qualities — pitch, pace, clarity, energy, emotional tone], with a clear American English accent."
  Sentence 3 — Personality → speaking style (draw directly from the dialogue lines if available):
    "{char_name} is [personality traits]. [He/She] speaks [how], as if [specific scenario that captures the character's essence]."
  Sentence 4 — Negative constraints + final quality goal:
    "Avoid [2–3 things to avoid based on this character]. Keep the voice [2–3 positive qualities] and easy for young children to understand."

REFERENCE EXAMPLE (Ruby, a rabbit character):
  "Create a warm, cheerful, and gentle female rabbit voice for a children's storybook character named Ruby.
  The voice should sound like a friendly children's animation character: light and soft, with clear pronunciation, gentle energy, and a comforting emotional tone, with a clear American English accent.
  Ruby is kind, helpful, and encouraging. She speaks in a bright and supportive way, as if she is happily offering help to a friend.
  Avoid sounding too adult, dramatic, or overly energetic. Keep the voice sweet, natural, and easy for young children to understand."

Now write the description for this character:

Character name: {char_name}
Gender: {g}
Age: {a}
Personality: {t}
Character context: {char_desc if char_desc else "A character in a children's storybook."}
Sample dialogue lines (use these to capture how the character actually speaks):
{sample_lines if sample_lines else "  (none available)"}"""

        clean_model_id = model_name.replace("models/", "")
        response = client.models.generate_content(model=clean_model_id, contents=prompt)
        result = response.text.strip()
        # 한국어 포함 방어
        korean_chars = sum(1 for c in result if '가' <= c <= '힣')
        if korean_chars > 3:
            return {"success": False, "error": "생성된 설명에 한국어가 포함되어 있습니다. 다시 시도해 주세요."}
        # American English 표현이 빠진 경우 마지막 문장 앞에 삽입
        american_keywords = ["american", "american english", "american accent"]
        if not any(kw in result.lower() for kw in american_keywords):
            result = result.rstrip(".") + ", with a clear American English accent."
        return {"success": True, "description": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
