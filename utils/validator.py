"""
Validator — 결정론적 검증 모듈
================================
Worker의 응답에서 코드 블록을 추출하고 Python 문법을 기계적으로 검증합니다.
LLM의 '말'이 아니라 '실행 가능성'만 봅니다.

검증 레이어:
- Layer 0: Sandbox 실행 검증 (런타임 에러 감지)
- Layer 1: ast.parse() 문법 검증 (구문 오류 감지)

핵심 원칙: "모델의 판단을 믿지 말고, 시스템(Rule)을 믿어라."
"""

import ast
import re
import logging
import subprocess
import tempfile
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── 코드 블록 추출 패턴 ──────────────────────────────────────
# ```python ... ``` 또는 ``` ... ``` 형태의 마크다운 코드 펜스 매칭
CODE_BLOCK_PATTERN = re.compile(
    r"```(?:python|py)?\s*\n(.*?)```",
    re.DOTALL,
)

# ── Sandbox 설정 ─────────────────────────────────────────────
SANDBOX_TIMEOUT = 5  # 초 (무한 루프 방어)


@dataclass
class ValidationResult:
    """검증 결과를 담는 데이터 클래스."""
    valid: bool
    has_code: bool          # 코드 블록이 포함되어 있었는지
    errors: list[str]       # 발견된 오류 목록
    code_blocks: list[str]  # 추출된 코드 블록들


def extract_code_blocks(text: str) -> list[str]:
    """
    마크다운 코드 펜스에서 Python 코드 블록을 추출합니다.

    Args:
        text: Worker 또는 LLM의 응답 텍스트

    Returns:
        추출된 코드 블록들의 리스트 (없으면 빈 리스트)
    """
    blocks = CODE_BLOCK_PATTERN.findall(text)
    # 빈 블록 필터링
    return [block.strip() for block in blocks if block.strip()]


def validate_syntax(code: str) -> dict:
    """
    ast.parse()를 사용하여 Python 코드의 문법을 검증합니다.

    Args:
        code: 검증할 Python 코드 문자열

    Returns:
        dict: {
            "valid": bool,    # 문법 유효 여부
            "error": str | None  # 오류 메시지 (없으면 None)
        }
    """
    try:
        ast.parse(code)
        return {"valid": True, "error": None}
    except SyntaxError as e:
        error_msg = f"Line {e.lineno}: {e.msg}"
        if e.text:
            error_msg += f" → `{e.text.strip()}`"
        return {"valid": False, "error": error_msg}


def execute_in_sandbox(code: str, timeout: int = SANDBOX_TIMEOUT) -> dict:
    """
    코드를 격리된 프로세스에서 실행하여 런타임 에러를 검증합니다.
    ast.parse()가 잡지 못하는 NameError, ImportError, TypeError 등을 감지합니다.

    Args:
        code: 실행할 Python 코드
        timeout: 실행 제한 시간 (초)

    Returns:
        dict: {
            "success": bool,
            "error": str | None,
            "stderr": str,
        }
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

        if result.returncode == 0:
            return {"success": True, "error": None, "stderr": ""}
        else:
            # stderr에서 마지막 에러 줄 추출
            stderr_lines = result.stderr.strip().split("\n")
            error_line = stderr_lines[-1] if stderr_lines else "Unknown error"
            return {
                "success": False,
                "error": error_line,
                "stderr": result.stderr,
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Execution timed out ({timeout}s) — possible infinite loop",
            "stderr": "",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Sandbox error: {e}",
            "stderr": "",
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def validate_response(
    response: str,
    run_sandbox: bool = False,
) -> ValidationResult:
    """
    Worker 응답에 대한 전체 검증 파이프라인을 실행합니다.

    1. 응답에서 코드 블록을 추출
    2. Layer 1: 각 코드 블록에 대해 ast.parse() 문법 검증
    3. Layer 0 (opt-in): Sandbox에서 실제 실행하여 런타임 에러 검증

    Args:
        response: Worker의 전체 응답 텍스트
        run_sandbox: True면 Sandbox 실행 검증도 수행 (기본: False)

    Returns:
        ValidationResult: 검증 결과
    """
    code_blocks = extract_code_blocks(response)

    # 코드 블록이 없으면 → 일반 텍스트 응답. 검증 스킵 (PASS)
    if not code_blocks:
        logger.debug("📝 코드 블록 없음 → 검증 스킵 (텍스트 응답)")
        return ValidationResult(
            valid=True,
            has_code=False,
            errors=[],
            code_blocks=[],
        )

    # ── Layer 1: ast.parse() 문법 검증 ───────────────────────
    errors = []
    for i, block in enumerate(code_blocks, 1):
        result = validate_syntax(block)
        if not result["valid"]:
            error_msg = f"[Block {i}/Syntax] {result['error']}"
            errors.append(error_msg)
            logger.warning(f"⚠️ 문법 오류 감지: {error_msg}")

    # ── Layer 0: Sandbox 실행 검증 (opt-in) ──────────────────
    if run_sandbox and not errors:
        for i, block in enumerate(code_blocks, 1):
            sandbox_result = execute_in_sandbox(block)
            if not sandbox_result["success"]:
                error_msg = f"[Block {i}/Runtime] {sandbox_result['error']}"
                errors.append(error_msg)
                logger.warning(f"⚠️ 런타임 오류 감지: {error_msg}")

    is_valid = len(errors) == 0

    if is_valid:
        layers = "ast" + ("+sandbox" if run_sandbox else "")
        logger.info(f"✅ 결정론적 검증 통과 ({layers}): {len(code_blocks)}개 코드 블록")
    else:
        logger.warning(
            f"❌ 결정론적 검증 실패: {len(errors)}/{len(code_blocks)}개 블록에서 오류"
        )

    return ValidationResult(
        valid=is_valid,
        has_code=True,
        errors=errors,
        code_blocks=code_blocks,
    )


def format_error_feedback(validation: ValidationResult) -> str:
    """
    검증 실패 시 Worker에게 전달할 에러 피드백 메시지를 생성합니다.

    Args:
        validation: 검증 결과

    Returns:
        Worker에게 전달할 에러 피드백 문자열
    """
    feedback_lines = [
        "⚠️ [CODE ERROR] 네가 작성한 코드에 오류가 발견되었다.",
        "다음 오류를 수정하여 다시 작성해라:",
        "",
    ]
    for error in validation.errors:
        feedback_lines.append(f"  • {error}")

    feedback_lines.extend([
        "",
        "수정된 코드만 다시 출력해라. 변명하지 마라.",
    ])

    return "\n".join(feedback_lines)

