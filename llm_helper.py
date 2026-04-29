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
            result_text = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL).group(1)
        elif "```" in result_text:
            result_text = re.search(r'```\s*(.*?)\s*```', result_text, re.DOTALL).group(1)
            
        data = json.loads(result_text)
        
        # UI 친화적인 캐릭터 딕셔너리로 변환
        char_dict = {char['name']: {**char, "description": ""} for char in data.get('characters', [])}
        
        return {
            "success": True, 
            "characters": char_dict, 
            "segments_metadata": data.get('segments', [])
        }
    except Exception as e:
        return {"success": False, "error": f"Gemini 분석 중 오류: {str(e)}"}
