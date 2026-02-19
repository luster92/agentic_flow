"""
Sandbox — 도구 실행 보안 게이트
=================================
모든 도구(파일 읽기, 디렉토리 조회, 코드 실행)가
실행 전 이 모듈의 검증을 통과해야 합니다.

보안 레이어:
- 경로 화이트리스트: 허용된 경로만 접근 가능
- 명령어 차단: 위험 명령어 실행 방지
- 리소스 제한: 실행 시간 및 메모리 제한
- Path Traversal 방지: 심볼릭 링크/상대경로 공격 차단
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── 보안 정책 모델 ─────────────────────────────────────────────

class SandboxPolicy(BaseModel):
    """샌드박스 보안 정책.

    ConfigLoader에서 base.yaml의 security 섹션을 읽어 생성합니다.
    """

    allowed_read_paths: list[str] = Field(
        default_factory=lambda: ["."],
        description="읽기 허용 경로 목록 (절대 또는 상대)",
    )
    allowed_write_paths: list[str] = Field(
        default_factory=lambda: ["./output/"],
        description="쓰기 허용 경로 목록",
    )
    blocked_commands: list[str] = Field(
        default_factory=lambda: [
            "rm -rf",
            "shutdown",
            "reboot",
            "mkfs",
            "dd if=",
            "chmod -R 777",
            "> /dev/",
            "curl.*|.*sh",
            "wget.*|.*sh",
        ],
        description="차단할 명령어/패턴 목록",
    )
    max_execution_time: int = Field(
        default=30,
        description="최대 실행 시간 (초)",
        ge=1,
        le=300,
    )
    max_memory_mb: int = Field(
        default=512,
        description="최대 메모리 사용량 (MB)",
        ge=64,
        le=4096,
    )
    enabled: bool = Field(
        default=True,
        description="샌드박스 활성화 여부",
    )


# ── 검증 결과 ──────────────────────────────────────────────────

class PathValidationResult(BaseModel):
    """경로 검증 결과."""
    allowed: bool
    path: str
    resolved_path: str
    reason: str = ""


class CommandValidationResult(BaseModel):
    """명령어 검증 결과."""
    allowed: bool
    command: str
    matched_pattern: str = ""
    reason: str = ""


# ── 샌드박스 매니저 ────────────────────────────────────────────

class SandboxManager:
    """도구 실행 전 보안 검증 게이트.

    모든 파일 접근 및 명령어 실행이 이 매니저를 통해
    화이트리스트/블랙리스트 검증을 받습니다.
    """

    def __init__(
        self,
        policy: SandboxPolicy | None = None,
        workspace_root: str | None = None,
    ) -> None:
        self.policy = policy or SandboxPolicy()
        self.workspace_root = Path(
            workspace_root or os.getcwd()
        ).resolve()

        # 허용 경로를 절대 경로로 정규화
        self._resolved_read_paths: list[Path] = []
        self._resolved_write_paths: list[Path] = []
        self._resolve_allowed_paths()

        # 차단 패턴을 정규식으로 컴파일
        self._blocked_patterns: list[re.Pattern[str]] = []
        self._compile_blocked_patterns()

        logger.info(
            f"🛡️ SandboxManager initialized "
            f"(enabled={self.policy.enabled}, "
            f"read_paths={len(self._resolved_read_paths)}, "
            f"blocked_cmds={len(self._blocked_patterns)})"
        )

    def _resolve_allowed_paths(self) -> None:
        """허용 경로를 절대 경로로 변환합니다."""
        for p in self.policy.allowed_read_paths:
            resolved = self._expand_path(p)
            self._resolved_read_paths.append(resolved)

        for p in self.policy.allowed_write_paths:
            resolved = self._expand_path(p)
            self._resolved_write_paths.append(resolved)

    def _expand_path(self, path_str: str) -> Path:
        """경로를 확장하고 절대 경로로 변환합니다."""
        expanded = os.path.expanduser(path_str)
        if not os.path.isabs(expanded):
            expanded = str(self.workspace_root / expanded)
        return Path(expanded).resolve()

    def _compile_blocked_patterns(self) -> None:
        """차단 명령어를 정규식으로 컴파일합니다."""
        for pattern in self.policy.blocked_commands:
            try:
                compiled = re.compile(re.escape(pattern))
                self._blocked_patterns.append(compiled)
            except re.error as e:
                logger.warning(
                    f"⚠️ Invalid blocked command pattern: "
                    f"{pattern} ({e})"
                )

    # ── 경로 검증 ─────────────────────────────────────────────

    def validate_path(
        self,
        path: str,
        mode: str = "read",
    ) -> PathValidationResult:
        """경로 접근 권한을 검증합니다.

        Args:
            path: 검증할 파일/디렉토리 경로
            mode: 접근 모드 ("read" | "write")

        Returns:
            PathValidationResult: 검증 결과
        """
        if not self.policy.enabled:
            return PathValidationResult(
                allowed=True,
                path=path,
                resolved_path=path,
                reason="Sandbox disabled",
            )

        try:
            target = Path(path).resolve()
        except (OSError, ValueError) as e:
            return PathValidationResult(
                allowed=False,
                path=path,
                resolved_path="<invalid>",
                reason=f"Invalid path: {e}",
            )

        resolved_str = str(target)

        # 심볼릭 링크 탐지 (Path Traversal 방지)
        try:
            original = Path(path)
            if original.is_symlink():
                logger.warning(
                    f"🛡️ Symlink detected: {path} → {target}"
                )
                return PathValidationResult(
                    allowed=False,
                    path=path,
                    resolved_path=resolved_str,
                    reason="Symbolic links are not allowed",
                )
        except (OSError, ValueError):
            pass

        # 화이트리스트 검증
        allowed_paths = (
            self._resolved_read_paths
            if mode == "read"
            else self._resolved_write_paths
        )

        for allowed in allowed_paths:
            allowed_str = str(allowed)
            if (
                resolved_str == allowed_str
                or resolved_str.startswith(allowed_str + os.sep)
            ):
                return PathValidationResult(
                    allowed=True,
                    path=path,
                    resolved_path=resolved_str,
                    reason=f"Matched allowed path: {allowed_str}",
                )

        return PathValidationResult(
            allowed=False,
            path=path,
            resolved_path=resolved_str,
            reason=(
                f"Path not in {mode} whitelist. "
                f"Resolved: {resolved_str}"
            ),
        )

    # ── 명령어 검증 ───────────────────────────────────────────

    def validate_command(self, command: str) -> CommandValidationResult:
        """명령어 실행 권한을 검증합니다.

        Args:
            command: 실행할 명령어 문자열

        Returns:
            CommandValidationResult: 검증 결과
        """
        if not self.policy.enabled:
            return CommandValidationResult(
                allowed=True,
                command=command,
                reason="Sandbox disabled",
            )

        normalized = command.strip().lower()

        for pattern in self._blocked_patterns:
            if pattern.search(normalized):
                logger.warning(
                    f"🛡️ Blocked command: '{command}' "
                    f"(matched: {pattern.pattern})"
                )
                return CommandValidationResult(
                    allowed=False,
                    command=command,
                    matched_pattern=pattern.pattern,
                    reason=f"Command matches blocked pattern: {pattern.pattern}",
                )

        return CommandValidationResult(
            allowed=True,
            command=command,
            reason="No blocked pattern matched",
        )

    # ── 유틸리티 ──────────────────────────────────────────────

    def get_policy_summary(self) -> dict[str, Any]:
        """현재 보안 정책 요약을 반환합니다."""
        return {
            "enabled": self.policy.enabled,
            "read_paths": [
                str(p) for p in self._resolved_read_paths
            ],
            "write_paths": [
                str(p) for p in self._resolved_write_paths
            ],
            "blocked_commands": len(self._blocked_patterns),
            "max_execution_time": self.policy.max_execution_time,
            "max_memory_mb": self.policy.max_memory_mb,
        }

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        workspace_root: str | None = None,
    ) -> SandboxManager:
        """설정 딕셔너리로부터 SandboxManager를 생성합니다.

        Args:
            config: security 섹션의 설정 딕셔너리
            workspace_root: 작업 디렉토리 루트

        Returns:
            SandboxManager 인스턴스
        """
        policy = SandboxPolicy(
            allowed_read_paths=config.get(
                "allowed_read_paths", ["."]
            ),
            allowed_write_paths=config.get(
                "allowed_write_paths", ["./output/"]
            ),
            blocked_commands=config.get("blocked_commands", []),
            max_execution_time=config.get("max_execution_time", 30),
            max_memory_mb=config.get("max_memory_mb", 512),
            enabled=config.get("sandbox_enabled", True),
        )
        return cls(policy=policy, workspace_root=workspace_root)
