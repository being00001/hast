import os

# Create directory
os.makedirs("/home/upopo/incubator", exist_ok=True)

content = r"""import click
import yaml
import json
import os
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

console = Console()

class IdeaStore:
    def __init__(self, root_dir):
        self.root = Path(root_dir).resolve() / ".ai" / "incubator"
        self.root.mkdir(parents=True, exist_ok=True)
    
    def save(self, idea_id, data):
        path = self.root / f"{idea_id}.yaml"
        with open(path, "w") as f:
            yaml.dump(data, f, sort_keys=False, allow_unicode=True)
        return path
    
    def load(self, idea_id):
        # Allow loading by just ID (e.g. idea_2024...) or full path
        if "/" in idea_id:
             path = Path(idea_id)
        else:
             path = self.root / f"{idea_id}.yaml"
             if not path.exists():
                 # try simple match
                 matches = list(self.root.glob(f"{idea_id}*.yaml"))
                 if matches:
                     path = matches[0]
        
        if not path.exists():
            return None
        with open(path, "r") as f:
            return yaml.safe_load(f)

@click.group()
def cli():
    """Being's Idea Incubator: Turn thoughts into actionable plans."""
    pass

@cli.command()
@click.argument("title")
@click.option("--problem", prompt="What is the problem?", help="The core problem statement")
@click.option("--goal", prompt="What is the goal?", help="Desired outcome")
@click.option("--project", default=".", help="Project root")
def new(title, problem, goal, project):
    """Start a new idea incubation session."""
    store = IdeaStore(project)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    idea_id = f"idea_{timestamp}"
    
    data = {
        "id": idea_id,
        "title": title,
        "status": "draft",
        "created_at": datetime.now().isoformat(),
        "core": {
            "problem": problem,
            "goal": goal
        },
        "analysis": {
            "risks": [],
            "requirements": [],
            "success_criteria": []
        }
    }
    
    path = store.save(idea_id, data)
    console.print(Panel(f"[bold green]Idea Created![/bold green]\nID: {idea_id}\nPath: {path}", title="Incubator"))

@cli.command()
@click.argument("idea_id")
@click.option("--project", default=".", help="Project root")
def refine(idea_id, project):
    """Simulate refining the idea (Adding structure)."""
    store = IdeaStore(project)
    data = store.load(idea_id)
    if not data:
        console.print(f"[bold red]Idea {idea_id} not found![/bold red]")
        return

    console.print(f"[bold yellow]Refining idea: {data['title']}...[/bold yellow]")
    
    # Simulate Logic
    analysis = data.setdefault("analysis", {})
    risks = analysis.setdefault("risks", [])
    reqs = analysis.setdefault("requirements", [])
    criteria = analysis.setdefault("success_criteria", [])

    # Heuristic refinement based on keywords
    goal_text = data["core"]["goal"].lower()
    prob_text = data["core"]["problem"].lower()

    if "money" in goal_text or "revenue" in goal_text:
        if "Market saturation" not in risks: risks.append("Market saturation")
        if "Payment gateway integration" not in reqs: reqs.append("Payment gateway integration")
        if "Revenue > $10" not in criteria: criteria.append("Revenue > $10")
    
    if "test" in prob_text or "bug" in prob_text:
         if "Unit test coverage > 80%" not in reqs: reqs.append("Unit test coverage > 80%")
         if "Zero critical bugs" not in criteria: criteria.append("Zero critical bugs")

    data["status"] = "refined"
    data["updated_at"] = datetime.now().isoformat()
    
    path = store.save(data["id"], data)
    console.print(Panel(yaml.dump(data["analysis"], allow_unicode=True), title="Refinement Result"))

@cli.command()
@click.argument("idea_id")
@click.option("--format", type=click.Choice(['decision', 'goal']), default='decision')
@click.option("--project", default=".", help="Project root")
def export(idea_id, format, project):
    """Export refined idea to Hast format."""
    store = IdeaStore(project)
    data = store.load(idea_id)
    if not data:
        console.print(f"[bold red]Idea not found![/bold red]")
        return
        
    project_path = Path(project).resolve()
    
    if format == 'decision':
        # Create a hast decision file
        decision_dir = project_path / ".ai" / "decisions"
        decision_dir.mkdir(parents=True, exist_ok=True)
        
        decision_id = f"D_{data['id'].upper()}"
        decision_file = decision_dir / f"{decision_id}.yaml"
        
        decision_data = {
            "id": decision_id,
            "status": "proposed",
            "context": {
                "problem": data["core"]["problem"],
                "goal": data["core"]["goal"],
                "risks": data["analysis"].get("risks", [])
            },
            "decision": {
                "criteria": ["feasibility", "impact", "cost"],
                "alternatives": [
                    {"name": "Option A (MVP)", "description": "Minimal implementation"},
                    {"name": "Option B (Full)", "description": "Full featured solution"}
                ]
            }
        }
        
        with open(decision_file, "w") as f:
            yaml.dump(decision_data, f, sort_keys=False, allow_unicode=True)
            
        console.print(Panel(f"[bold green]Exported to Decision![/bold green]\nPath: {decision_file}", title="Export Success"))

    elif format == 'goal':
        # Simulate Goal format
        new_goal = {
            "id": f"G_{data['id'].split('_')[1]}",
            "title": data["title"],
            "status": "proposed",
            "description": f"Problem: {data['core']['problem']}\nGoal: {data['core']['goal']}",
            "acceptance_criteria": data["analysis"].get("success_criteria", [])
        }
        
        console.print(Panel(yaml.dump(new_goal, allow_unicode=True), title="Goal Draft (Ready to Append)"))

if __name__ == "__main__":
    cli()
"""

with open("/home/upopo/incubator/incubator.py", "w") as f:
    f.write(content)
print("Incubator tool created!")
