from google import genai
import sys

def test_key(api_key):
    try:
        client = genai.Client(api_key=api_key)
        print("Listing models...")
        for model in client.models.list():
            print(f"- {model.name}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_key(sys.argv[1])
    else:
        print("Usage: python test_models.py <API_KEY>")
