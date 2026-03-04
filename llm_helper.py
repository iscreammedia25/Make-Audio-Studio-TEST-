from google import genai
import json
import re

def extract_characters_via_gemini(api_key, script_text):
    """
    Gemini API를 호출하여 동화 대본에서 캐릭터 이름, 성별, 나이, 무드를 추출합니다.
    """
    if not api_key:
        return {"success": False, "error": "Gemini API 키가 입력되지 않았습니다."}
    
    try:
        # Initialize the new SDK client
        client = genai.Client(api_key=api_key)
        
        prompt = f"""
다음은 동화 대본입니다. 이 대본에 등장하여 **직접 대사(" " 또는 ' ' 안의 말)를 하거나 생각 문장(따옴표 유무 무관)을 말하는 캐릭터만** 정확히 추출해주세요. 대사가 전혀 없는 배경 인물이나 단순 언급된 대상은 절대 포함하지 마세요.
고유명사(예: Milo, Rosy)뿐만 아니라, 극중 배역을 나타내는 일반명사(예: son, princess, merchant, woodcutter, wolf 등)도 캐릭터로 취급합니다.

**[중요 주의사항 - 대명사 화자 추적]**
만약 대사를 치는 주어가 대명사(예: He said "...", She asked "...")로 되어 있다면, 반드시 앞 문맥을 살펴보고 그 대명사가 지칭하는 **원래 캐릭터의 이름(고유명사 또는 일반명사)**을 찾아서 그 이름표로 추출해야 합니다. 
(예: 앞서 'The princess'가 등장했고 뒤에서 'She said'라고 말한다면, 화자는 'She'가 아니라 'Princess'로 추출해야 함)

반드시 아래 JSON 배열 형식으로만 답변을 작성하세요. 다른 텍스트는 덧붙이지 마세요.
[
    {{
        "name": "캐릭터의 영문 이름 (대명사 불가, 단어의 첫 글자는 대문자, 예: Son, Princess)",
        "gender": "남성" 또는 "여성" 또는 "중성" (대본 문맥이나 대명사를 보고 판단),
        "age": "아동" 또는 "청소년" 또는 "성인" 또는 "노인" (문맥상 추정, 모르면 "성인"),
        "tone": "보통" 또는 "활기찬" 또는 "차분한" 등 (캐릭터의 성격이나 상황을 묘사하는 짧은 단어 1-2개)
    }}
]

대본 내용:
{script_text}
"""
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        result_text = response.text.strip()
        
        # Markdown JSON 블록 제거 (```json ... ```)
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        if result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
            
        result_text = result_text.strip()
        
        try:
            characters_list = json.loads(result_text)
            
            # 딕셔너리 형태로 변환하여 반환 (UI에서 사용하기 편하게 구성)
            characters_dict = {}
            for char in characters_list:
                name = char.get("name", "").strip()
                if not name: continue
                
                characters_dict[name] = {
                    "name": name,
                    "gender": char.get("gender", "중성"),
                    "age": char.get("age", "성인"),
                    "tone": char.get("tone", "보통"),
                    "description": "" # 초기화
                }
            
            return {"success": True, "characters": characters_dict}
            
        except json.JSONDecodeError:
            return {"success": False, "error": f"JSON 파싱 실패. AI의 응답 형식이 올바르지 않습니다.\n\nAI 응답:\n{result_text}"}
            
    except Exception as e:
        return {"success": False, "error": f"Gemini API 호출 중 오류 발생: {str(e)}"}
