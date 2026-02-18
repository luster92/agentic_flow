"""
Tools Module — Worker의 감각 기관
================================
Worker 에이전트가 외부 세계(파일시스템, 쉘 등)와 상호작용하기 위한 도구 모음입니다.
OpenAI Function Calling 규격(JSON Schema)을 준수합니다.

Security:
- 모든 도구는 실행 전 경로 유효성 및 권한을 검증해야 합니다. (Path Traversal 방지)
- Sandbox 내에서 실행되는 것을 권장합니다.
"""

import os
import glob
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from pydantic import BaseModel, ValidationError, Field
from typing import Optional

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """모든 도구의 기본 추상 클래스."""
    name: str
    description: str
    parameters: dict
    input_model: Optional[type[BaseModel]] = None  # Pydantic 검증 모델

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """도구를 실행하고 결과를 문자열로 반환합니다."""
        pass

    async def validate_and_execute(self, **kwargs) -> str:
        """Pydantic으로 입력을 검증한 후 실행합니다.

        잘못된 인자가 감지되면 런타임 에러 대신
        에이전트가 이해 가능한 피드백 메시지를 반환합니다.
        """
        if self.input_model is not None:
            try:
                validated = self.input_model(**kwargs)
                kwargs = validated.model_dump()
            except ValidationError as e:
                errors = []
                for err in e.errors():
                    field = ".".join(str(loc) for loc in err["loc"])
                    errors.append(f"  - {field}: {err['msg']}")
                return (
                    f"⚠️ Tool Input Error ({self.name}):\n"
                    + "\n".join(errors)
                    + "\n올바른 형식으로 다시 시도해 주세요."
                )
        return await self.execute(**kwargs)

    def to_schema(self) -> dict:
        """OpenAI Function Calling용 JSON Schema를 반환합니다."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ── Pydantic Input Models ──────────────────────────────────────

class FileReadInput(BaseModel):
    path: str = Field(..., min_length=1, description="파일 경로")

class ListDirInput(BaseModel):
    path: str = Field(default=".", description="디렉토리 경로")


class FileReadTool(BaseTool):
    """파일 내용을 읽어오는 도구."""
    name = "read_file"
    description = "지정된 경로의 파일 내용을 읽습니다. 소스 코드 분석이나 설정 확인 시 사용합니다."
    input_model = FileReadInput
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "읽을 파일의 상대 경로 또는 절대 경로 (예: 'main.py', 'utils/tools.py')",
            }
        },
        "required": ["path"],
    }

    async def execute(self, path: str) -> str:
        try:
            target_path = Path(path).resolve()
            
            # Simple Security Check: 현재 작업 디렉토리 내부인지 확인 (일단은 느슨하게 허용하되 로깅)
            cwd = Path.cwd().resolve()
            if not str(target_path).startswith(str(cwd)):
                logger.warning(f"⚠️ [Security] 외부 경로 접근 시도: {target_path}")

            if not target_path.exists():
                return f"❌ Error: File not found: {path}"
            
            if not target_path.is_file():
                return f"❌ Error: Not a file: {path}"

            # 텍스트 파일 읽기 (UTF-8)
            content = target_path.read_text(encoding="utf-8")
            return content

        except Exception as e:
            return f"❌ Error reading file: {e}"


class ListDirTool(BaseTool):
    """디렉토리 목록을 조회하는 도구."""
    name = "list_dir"
    description = "지정된 디렉토리의 파일 및 하위 폴더 목록을 조회합니다. 프로젝트 구조 파악 시 사용합니다."
    input_model = ListDirInput
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "조회할 디렉토리 경로 (기본값: 현재 디렉토리 '.')",
                "default": ".",
            }
        },
        "required": [],
    }

    async def execute(self, path: str = ".") -> str:
        try:
            target_path = Path(path).resolve()
            
            if not target_path.exists():
                return f"❌ Error: Directory not found: {path}"
            
            if not target_path.is_dir():
                return f"❌ Error: Not a directory: {path}"

            items = []
            for item in target_path.iterdir():
                # .git, .venv, __pycache__ 등은 숨김 처리
                if item.name.startswith(".") or item.name == "__pycache__":
                    continue
                
                kind = "📁" if item.is_dir() else "📄"
                items.append(f"{kind} {item.name}")

            return "\n".join(sorted(items)) or "(Empty directory)"

        except Exception as e:
            return f"❌ Error listing directory: {e}"


# 사용 가능한 도구 목록
AVAILABLE_TOOLS: list[BaseTool] = [
    FileReadTool(),
    ListDirTool(),
]

def get_tool_schemas() -> list[dict]:
    """Worker에게 전달할 도구 스키마 목록을 반환합니다."""
    return [tool.to_schema() for tool in AVAILABLE_TOOLS]

def get_tool_by_name(name: str) -> BaseTool | None:
    """이름으로 도구 인스턴스를 찾습니다."""
    for tool in AVAILABLE_TOOLS:
        if tool.name == name:
            return tool
    return None
