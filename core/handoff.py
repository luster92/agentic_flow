import os
import json
import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("handoff")

class HandoffData(BaseModel):
    current_goal: str = ""
    progress: list[str] = Field(default_factory=list)
    failed_attempts: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class HandoffManager:
    """HANDOFF.md 생성 및 파싱을 담당합니다."""
    
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self.handoff_file = os.path.join(self.workspace_dir, "HANDOFF.md")

    def generate_handoff(self, data: HandoffData) -> None:
        """현재 상태를 기반으로 HANDOFF.md 파일을 생성합니다."""
        
        content = [
            "# Agent Handoff Document\n",
            "## Current Goal",
            f"{data.current_goal}\n",
            "## Progress",
            *[f"- {p}" for p in data.progress],
            "\n## Failed Attempts",
            *[f"- {f}" for f in data.failed_attempts],
            "\n## Next Steps",
            *[f"- {n}" for n in data.next_steps]
        ]
        
        try:
            with open(self.handoff_file, "w", encoding="utf-8") as f:
                f.write("\n".join(content))
            logger.info(f"✅ HANDOFF.md created at {self.handoff_file}")
        except Exception as e:
            logger.error(f"❌ Failed to write HANDOFF.md: {e}")

    def load_handoff(self) -> Optional[HandoffData]:
        """HANDOFF.md 파일을 읽어 데이터를 파싱합니다."""
        if not os.path.exists(self.handoff_file):
            return None

        try:
            with open(self.handoff_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            data = HandoffData()
            current_section = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                if line.startswith("## Current Goal"):
                    current_section = "goal"
                elif line.startswith("## Progress"):
                    current_section = "progress"
                elif line.startswith("## Failed Attempts"):
                    current_section = "failed"
                elif line.startswith("## Next Steps"):
                    current_section = "next"
                elif line.startswith("- ") and current_section != "goal":
                    val = line[2:]
                    if current_section == "progress":
                        data.progress.append(val)
                    elif current_section == "failed":
                        data.failed_attempts.append(val)
                    elif current_section == "next":
                        data.next_steps.append(val)
                elif current_section == "goal" and not line.startswith("#"):
                    data.current_goal += line + "\n"
                    
            data.current_goal = data.current_goal.strip()
            return data
            
        except Exception as e:
            logger.error(f"❌ Failed to parse HANDOFF.md: {e}")
            return None

    def clear_handoff(self) -> None:
        """HANDOFF.md 파일을 삭제합니다."""
        if os.path.exists(self.handoff_file):
            os.remove(self.handoff_file)
            logger.info("🗑️ HANDOFF.md cleared")
