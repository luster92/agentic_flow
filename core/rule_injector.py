import os
import re
import logging
from typing import List

logger = logging.getLogger("rule_injector")

class RuleInjector:
    """CLAUDE.md 파일을 파싱하여 메타-거버넌스 규칙과 의도(Intent)를 시스템 프롬프트에 주입합니다."""
    
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self.rule_file = os.path.join(self.workspace_dir, "CLAUDE.md")

    def get_injected_rules(self) -> str:
        """규칙을 파싱하고 의도를 덧붙여 반환합니다."""
        if not os.path.exists(self.rule_file):
            return ""

        try:
            with open(self.rule_file, "r", encoding="utf-8") as f:
                content = f.read()

            injected_lines: List[str] = []
            
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                
                # 'DO NOT:' 형태의 금지 규칙에 "왜 안 되는지" 휴리스틱 의도 추가
                if line.upper().startswith("- DO NOT:") or line.upper().startswith("DO NOT:"):
                    reason = "Reason: To prevent runtime errors, security vulnerabilities, or architecture fragmentation."
                    if "type" in line.lower() or "any" in line.lower():
                        reason = "Reason: To prevent runtime type errors and ensure maintainability in our strictly typed codebase."
                    elif "commit" in line.lower() or "env" in line.lower():
                        reason = "Reason: To strictly prevent credential leaks and ensure enterprise security."
                    
                    line = f"{line} ({reason})"
                    
                injected_lines.append(line)

            formatted_rules = "\n".join(injected_lines)
            return f"\n\n[PROJECT RULES (CLAUDE.md)]\n{formatted_rules}\n"
            
        except Exception as e:
            logger.error(f"❌ Failed to parse CLAUDE.md: {e}")
            return ""
