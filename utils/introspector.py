"""
Introspector — 런타임 라이브러리 검사 도구
==========================================
LLM의 학습 데이터 시점(Knowledge Cutoff)과 실제 설치된 라이브러리 간의
불일치를 해소하기 위한 자기 성찰(Introspection) 도구입니다.

핵심 원칙: "네 기억을 믿지 말고, 지금 설치된 라이브러리를 믿어라."

기능:
1. get_package_version() — 설치된 패키지 버전 확인
2. inspect_library() — 패키지의 실제 사용 가능한 객체 목록 확인
3. generate_context() — Golden Snippet + 패키지 버전을 컨텍스트로 반환
"""

import importlib
import logging
import os
from importlib import metadata as importlib_metadata
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Golden Snippet 파일 경로 ──────────────────────────────────
DOCS_DIR = Path(__file__).parent.parent / "docs"
GOLDEN_SNIPPET_FILE = DOCS_DIR / "latest_syntax.md"

# ── 모니터링할 핵심 패키지 목록 ───────────────────────────────
MONITORED_PACKAGES = [
    "openai",
    "pydantic",
    "litellm",
    "langchain",
    "langchain-core",
    "langchain-openai",
]


def get_package_version(package_name: str) -> str | None:
    """
    설치된 패키지의 버전을 반환합니다.

    Args:
        package_name: 패키지 이름 (예: 'openai')

    Returns:
        버전 문자열 (예: '2.21.0'), 미설치 시 None
    """
    try:
        return importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        return None


def inspect_library(
    lib_name: str,
    target_object: str | None = None,
) -> dict:
    """
    설치된 라이브러리의 실제 구조를 검사합니다.
    모델이 구버전 함수를 참조할 때, 실제 사용 가능한 객체 목록을 제공합니다.

    Args:
        lib_name: 라이브러리 이름 (예: 'openai')
        target_object: 찾으려는 특정 객체명 (예: 'ChatCompletion')

    Returns:
        dict: {
            "installed": bool,      # 설치 여부
            "version": str | None,  # 버전
            "target_found": bool | None,  # 특정 객체 존재 여부
            "available": list[str], # 사용 가능한 공개 객체 목록
            "message": str,         # 사람이 읽을 수 있는 결과 메시지
        }
    """
    version = get_package_version(lib_name)

    try:
        module = importlib.import_module(lib_name)
    except ImportError:
        return {
            "installed": False,
            "version": None,
            "target_found": None,
            "available": [],
            "message": f"❌ '{lib_name}' is not installed.",
        }

    # 공개 객체만 필터링 (언더스코어로 시작하지 않는 것)
    available = [name for name in dir(module) if not name.startswith("_")]

    if target_object:
        found = hasattr(module, target_object)
        if found:
            msg = f"✅ '{target_object}' exists in {lib_name} v{version}."
        else:
            msg = (
                f"❌ '{target_object}' NOT found in {lib_name} v{version}.\n"
                f"   Available objects: {', '.join(available[:20])}"
            )
        return {
            "installed": True,
            "version": version,
            "target_found": found,
            "available": available,
            "message": msg,
        }

    return {
        "installed": True,
        "version": version,
        "target_found": None,
        "available": available,
        "message": f"📦 {lib_name} v{version}: {', '.join(available[:15])}...",
    }


def _load_golden_snippet() -> str:
    """Golden Snippet 파일을 로드합니다."""
    if GOLDEN_SNIPPET_FILE.exists():
        content = GOLDEN_SNIPPET_FILE.read_text(encoding="utf-8")
        logger.debug(f"📄 Golden Snippet 로드 완료: {GOLDEN_SNIPPET_FILE}")
        return content
    else:
        logger.warning(f"⚠️ Golden Snippet 파일 없음: {GOLDEN_SNIPPET_FILE}")
        return ""


def get_installed_versions() -> dict[str, str | None]:
    """모니터링 대상 패키지들의 설치 버전을 일괄 확인합니다."""
    versions = {}
    for pkg in MONITORED_PACKAGES:
        versions[pkg] = get_package_version(pkg)
    return versions


def generate_context() -> str:
    """
    Worker에게 주입할 Knowledge Context를 생성합니다.
    Golden Snippet + 설치된 패키지 버전 정보를 결합합니다.

    Returns:
        Worker 시스템 프롬프트에 추가할 컨텍스트 문자열
    """
    parts = []

    # 1. Golden Snippet
    snippet = _load_golden_snippet()
    if snippet:
        parts.append("## [Knowledge Context] 최신 API 문법 참조")
        parts.append("아래 문법은 네 학습 데이터보다 우선순위가 높다. 반드시 따라라.\n")
        parts.append(snippet)

    # 2. 설치된 패키지 버전
    versions = get_installed_versions()
    installed = {k: v for k, v in versions.items() if v is not None}

    if installed:
        parts.append("\n## [Runtime Info] 현재 설치된 패키지 버전")
        for pkg, ver in installed.items():
            parts.append(f"- {pkg}: v{ver}")
        parts.append("\n위 버전에 맞는 API를 사용해라. 구버전 문법을 사용하지 마라.")

    context = "\n".join(parts)

    if context:
        logger.info(
            f"📚 Knowledge Context 생성 완료 "
            f"(snippet={'Yes' if snippet else 'No'}, "
            f"packages={len(installed)}개)"
        )

    return context
