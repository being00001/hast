import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys

# Pre-defined responses for the scenario
ARCHITECT_RESPONSE = """
```gherkin:features/health.feature
Feature: Health Check
  Scenario: Health Endpoint
    When I request /health
    Then the response status code should be 200
    And the response body should contain "ok"
```

```yaml:goals_append.yaml
- id: G_HEALTH
  title: Implement Health Check
  status: active
  spec_file: features/health.feature
```
"""

WORKER_TEST_RESPONSE = """
```python:tests/test_health.py
import pytest
from pytest_bdd import scenario, when, then

@scenario('../../features/health.feature', 'Health Endpoint')
def test_health():
    pass

@pytest.fixture
def client():
    from src.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)

@when("I request /health")
def request_health(client):
    pytest.response = client.get("/health")

@then("the response status code should be 200")
def check_status():
    assert pytest.response.status_code == 200

@then('the response body should contain "ok"')
def check_body():
    assert pytest.response.json() == {"status": "ok"}
```
"""

WORKER_IMPL_RESPONSE = """
```python:src/main.py
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "ok"}
```
"""

class MockLLMHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        data = json.loads(post_data.decode('utf-8'))
        
        messages = data.get("messages", [])
        prompt = messages[-1]["content"] if messages else ""
        model = data.get("model", "")
        
        print(f"[FakeLLM] Received request for model: {model}")
        print(f"[FakeLLM] Prompt snippet: {prompt[:50]}...")

        response_content = "I don't know."
        
        if "Architect" in prompt or model == "fake-architect":
            response_content = ARCHITECT_RESPONSE
        elif "pytest-bdd" in prompt:
            response_content = WORKER_TEST_RESPONSE
        elif "Implement the logic" in prompt:
            response_content = WORKER_IMPL_RESPONSE

        # OpenAI-compatible response format
        response_data = {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": 1677652288,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_content
                },
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
        }

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response_data).encode('utf-8'))

    def log_message(self, format, *args):
        # Silence default logging
        pass

if __name__ == "__main__":
    port = 8888
    print(f"Fake LLM Server running on port {port}")
    server = HTTPServer(('localhost', port), MockLLMHandler)
    server.serve_forever()
