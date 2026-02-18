"""
Knowledge Updater — 자가 진화 오답 노트
========================================
에이전트가 오류를 겪을 때마다 Golden Snippet(docs/latest_syntax.md)을
자동으로 갱신하는 Learning Loop 모듈입니다.

두 가지 갱신 모드:
1. Error-Driven Update: 검증 실패 → 재시도 성공 시 오답 자동 기록
2. Install-Time Scan: 패키지 구조를 inspect로 추출하여 문서 추가

핵심 원칙: "같은 실수를 두 번 하지 마라."
"""

import importlib
import inspect
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Golden Snippet 파일 경로 ──────────────────────────────────
DOCS_DIR = Path(__file__).parent.parent / "docs"
GOLDEN_SNIPPET_FILE = DOCS_DIR / "latest_syntax.md"

# ── 자동 생성 마커 ───────────────────────────────────────────
AUTO_SECTION_MARKER = "<!-- AUTO-GENERATED: Learning Loop -->"


def record_learning(
    error_message: str,
    original_code: str,
    fixed_code: str,
    package_name: str | None = None,
) -> bool:
    """
    Worker가 검증 실패 후 재시도 성공했을 때, 오답 노트를 자동 기록합니다.

    Args:
        error_message: 발생했던 에러 메시지
        original_code: 에러가 있던 원본 코드 (첫 200자)
        fixed_code: 수정된 코드 (첫 200자)
        package_name: 관련 패키지 이름 (옵션)

    Returns:
        기록 성공 여부
    """
    try:
        DOCS_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        pkg_label = f" ({package_name})" if package_name else ""

        entry = f"""
{AUTO_SECTION_MARKER}
### 🔴 오답 노트{pkg_label} — {timestamp}

**에러:** `{error_message[:150]}`

❌ 잘못된 코드:
```python
{original_code[:300]}
```

✅ 수정된 코드:
```python
{fixed_code[:300]}
```

---
"""
        with open(GOLDEN_SNIPPET_FILE, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.info(f"📝 [Learning Loop] 오답 노트 기록 완료{pkg_label}")
        return True

    except Exception as e:
        logger.error(f"❌ [Learning Loop] 오답 노트 기록 실패: {e}")
        return False


def scan_package(package_name: str) -> str | None:
    """
    설치된 패키지의 핵심 구조를 inspect로 추출하여 요약합니다.

    Args:
        package_name: 스캔할 패키지 이름

    Returns:
        요약 문자열, 실패 시 None
    """
    try:
        module = importlib.import_module(package_name)
    except ImportError:
        logger.warning(f"⚠️ '{package_name}' is not installed.")
        return None

    # 패키지 버전
    version = "unknown"
    try:
        from importlib import metadata
        version = metadata.version(package_name)
    except Exception:
        pass

    # 공개 클래스와 함수 추출
    classes = []
    functions = []

    for name, obj in inspect.getmembers(module):
        if name.startswith("_"):
            continue
        if inspect.isclass(obj):
            # 클래스의 공개 메서드 추출
            methods = [
                m for m in dir(obj)
                if not m.startswith("_") and callable(getattr(obj, m, None))
            ]
            classes.append({
                "name": name,
                "methods": methods[:10],
            })
        elif inspect.isfunction(obj):
            sig = ""
            try:
                sig = str(inspect.signature(obj))
            except (ValueError, TypeError):
                pass
            functions.append({"name": name, "signature": sig})

    # 요약 생성
    lines = [f"## {package_name} v{version} (Auto-scanned)"]

    if classes:
        lines.append("\n### 주요 클래스")
        for cls in classes[:8]:
            methods_str = ", ".join(cls["methods"][:5])
            if cls["methods"]:
                lines.append(f"- `{cls['name']}` — methods: `{methods_str}`")
            else:
                lines.append(f"- `{cls['name']}`")

    if functions:
        lines.append("\n### 주요 함수")
        for fn in functions[:10]:
            lines.append(f"- `{fn['name']}{fn['signature']}`")

    summary = "\n".join(lines)
    return summary


def scan_and_save(package_name: str) -> bool:
    """
    패키지를 스캔하고 결과를 Golden Snippet에 자동 추가합니다.

    Args:
        package_name: 스캔할 패키지 이름

    Returns:
        성공 여부
    """
    summary = scan_package(package_name)
    if summary is None:
        return False

    try:
        DOCS_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        entry = f"""
{AUTO_SECTION_MARKER}
{summary}
> Auto-generated on {timestamp}

---
"""
        with open(GOLDEN_SNIPPET_FILE, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.info(f"📦 [Learning Loop] {package_name} 스캔 결과 저장 완료")
        return True

    except Exception as e:
        logger.error(f"❌ [Learning Loop] 스캔 결과 저장 실패: {e}")
        return False
