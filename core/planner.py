import json
from dataclasses import dataclass, field
from typing import List, Optional
import logging
from openai import AsyncOpenAI

logger = logging.getLogger("planner")

@dataclass
class SubTask:
    id: str
    description: str
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending" # pending, running, completed, failed
    result: Optional[str] = None

@dataclass
class TaskPlan:
    original_request: str
    tasks: List[SubTask]
    
    def get_next_tasks(self) -> List[SubTask]:
        """Returns tasks whose dependencies are completed."""
        completed_ids = {t.id for t in self.tasks if t.status == "completed"}
        return [
            t for t in self.tasks 
            if t.status == "pending" and all(dep in completed_ids for dep in t.dependencies)
        ]

    def all_completed(self) -> bool:
        return all(t.status == "completed" for t in self.tasks)


class TaskPlanner:
    def __init__(self, base_url: str):
        self.base_url = base_url

    async def create_plan(self, user_input: str) -> Optional[TaskPlan]:
        """사용자 입력을 서브 태스크(DAG)로 분해합니다."""
        client = AsyncOpenAI(base_url=self.base_url, api_key="not-needed")
        
        system_prompt = (
            "You are an expert software architect. Your job is to break down complex user requests "
            "into a sequence of independent, sequential sub-tasks. "
            "If the request is simple (e.g. asking a question, greeting, or minor fix), output an empty task list.\n"
            "Format the output strictly as a JSON object:\n"
            "{\n"
            "  \"is_complex\": boolean,\n"
            "  \"tasks\": [\n"
            "    {\"id\": \"task_1\", \"description\": \"Detailed description...\", \"dependencies\": []},\n"
            "    {\"id\": \"task_2\", \"description\": \"...\", \"dependencies\": [\"task_1\"]}\n"
            "  ]\n"
            "}\n"
            "Do NOT include markdown block characters like ```json."
        )

        try:
            response = await client.chat.completions.create(
                model="cloud-pm-gemini", # default for planning
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input}
                ],
                temperature=0.2,
                max_tokens=2048
            )
            
            content = response.choices[0].message.content or "{}"
            # cleanup potential parsing issues
            if content.startswith("```json"):
                content = content[7:-3]
            elif content.startswith("```"):
                content = content[3:-3]
            
            content = content.strip()
            data = json.loads(content)
            
            if data.get("is_complex", False) and data.get("tasks"):
                tasks = [
                    SubTask(
                        id=t["id"],
                        description=t["description"],
                        dependencies=t.get("dependencies", [])
                    )
                    for t in data["tasks"]
                ]
                return TaskPlan(original_request=user_input, tasks=tasks)
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to create plan: {e}")
            return None
