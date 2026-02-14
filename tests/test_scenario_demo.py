"""Integration test simulating the Health Check Scenario."""

import sys
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

# Ensure src is in path
sys.path.insert(0, str(Path.cwd() / "src"))

from devf.cli import main
from devf.core.config import Config, ModelConfig, RolesConfig


@pytest.fixture
def demo_root(tmp_path):
    """Setup a mock project environment."""
    (tmp_path / ".ai").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "features").mkdir()
    
    # Config
    (tmp_path / ".ai" / "config.yaml").write_text("""
test_command: pytest
ai_tool: dummy {prompt}
roles:
  architect:
    model: architect-gpt
  worker:
    model: worker-gpt
""", encoding="utf-8")

    # Empty goals
    (tmp_path / ".ai" / "goals.yaml").write_text("goals: []", encoding="utf-8")
    
    # Initialize git (needed for devf auto)
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp_path, check=True)
    
    return tmp_path


def test_scenario_health_check(demo_root):
    """
    Simulates:
    1. devf plan "Add health check"
    2. Architect -> Creates feature & goal
    3. auto -> Test Gen (Red)
    4. auto -> Impl (Green)
    """
    
    # --- MOCKED RESPONSES ---
    
    # 1. Architect Response
    architect_resp = """
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

    # 2. Worker Response 1 (Test Generation)
    worker_test_resp = """
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

    # 3. Worker Response 2 (Implementation)
    worker_impl_resp = """
    ```python:src/main.py
    from fastapi import FastAPI
    
    app = FastAPI()
    
    @app.get("/health")
    def health_check():
        return {"status": "ok"}
    ```
    """
    
    # We need a side_effect for completion to return different responses based on the prompt/model
    def completion_side_effect(*args, **kwargs):
        model = kwargs.get("model")
        messages = kwargs.get("messages", [])
        prompt = messages[0]["content"] if messages else ""
        
        mock_res = MagicMock()
        
        if model == "architect-gpt":
            mock_res.choices[0].message.content = architect_resp
            return mock_res
        
        if model == "worker-gpt":
            if "Generate pytest-bdd step definitions" in prompt:
                mock_res.choices[0].message.content = worker_test_resp
            elif "Implement the logic" in prompt:
                mock_res.choices[0].message.content = worker_impl_resp
            else:
                mock_res.choices[0].message.content = "Unknown prompt"
            return mock_res
            
        return mock_res

    # Mock subprocess.run for pytest
    # We need to simulate:
    # 1. Initial test run (during build_prompt) -> Fail or Pass?
    # 2. After Test Gen -> Fail (Red)
    # 3. After Impl -> Pass (Green)
    
    original_run = subprocess.run
    
    def subprocess_side_effect(command, *args, **kwargs):
        # Allow git commands to pass through to real git
        cmd_str = command if isinstance(command, str) else " ".join(command)
        
        if "git" in cmd_str:
            return original_run(command, *args, **kwargs)
            
        # Mock pytest
        if "pytest" in cmd_str:
            res = MagicMock()
            res.stdout = "Test Output"
            res.stderr = ""
            
            # Logic to determine pass/fail based on file existence
            cwd = kwargs.get("cwd", str(demo_root))
            has_impl = (Path(cwd) / "src/main.py").exists()
            has_test = (Path(cwd) / "tests/test_health.py").exists()
            
            if has_test and has_impl:
                res.returncode = 0 # Green
            elif has_test and not has_impl:
                res.returncode = 1 # Red
            else:
                res.returncode = 1 # No tests yet? or Pass if no tests?
                # devf auto checks "test_command"
                # If no tests exist yet, pytest might exit 5 (no tests collected)
                res.returncode = 5 
                
            return res
            
        return original_run(command, *args, **kwargs)


    # --- EXECUTION ---
    
    with patch("devf.core.runners.llm.completion", side_effect=completion_side_effect):
        with patch("subprocess.run", side_effect=subprocess_side_effect):
            # We also need to patch find_root because CliRunner isolates fs?
            # Actually, we pass 'demo_root' but find_root looks for .ai
            # demo_root has .ai, so if we cd into it, it works.

            runner = CliRunner()
            with runner.isolated_filesystem(temp_dir=demo_root):
                # We are now inside demo_root

                # Run 'devf plan'
                result = runner.invoke(main, ["plan", "Add health check"])

                # Output debugging
                print(result.output)
                if result.exception:
                    import traceback
                    traceback.print_exception(*result.exc_info)

                assert result.exit_code == 0
                assert "Goal G_HEALTH created" in result.output

                # Verify Architect artifacts
                assert (demo_root / "features/health.feature").exists()
                assert "G_HEALTH" in (demo_root / ".ai/goals.yaml").read_text()

                # Keep working tree clean before auto loop.
                subprocess.run(["git", "add", "-A"], cwd=str(demo_root), check=True)
                subprocess.run(
                    ["git", "commit", "-m", "chore: plan artifacts"],
                    cwd=str(demo_root),
                    check=True,
                )

                # Run 'devf auto G_HEALTH'
                result_auto = runner.invoke(main, ["auto", "G_HEALTH"])

                print(result_auto.output)
                if result_auto.exception:
                     import traceback
                     traceback.print_exception(*result_auto.exc_info)

                assert result_auto.exit_code == 0

                # Verify Worker Artifacts
                assert (demo_root / "tests/test_health.py").exists()
                assert (demo_root / "src/main.py").exists()

                # Verify Status
                goals_txt = (demo_root / ".ai/goals.yaml").read_text()
                assert "status: done" in goals_txt
