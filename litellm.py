import json
import urllib.request
import urllib.error

def completion(model, messages, **kwargs):
    url = "http://localhost:8888/chat/completions"
    data = {
        "model": model,
        "messages": messages
    }
    req = urllib.request.Request(
        url, 
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            # Wrap result in an object structure similar to what code expects
            # response.choices[0].message.content
            class Message:
                def __init__(self, content):
                    self.content = content
            
            class Choice:
                def __init__(self, message):
                    self.message = Message(message["content"])
            
            class Response:
                def __init__(self, choices):
                    self.choices = [Choice(c["message"]) for c in choices]
            
            return Response(result["choices"])
            
    except urllib.error.URLError as e:
        raise Exception(f"Failed to call Fake LLM: {e}")
