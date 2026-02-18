#!/usr/bin/env python3
"""
Package Scanner CLI — 패키지 자동 매뉴얼 생성
=============================================
새 패키지를 설치한 후 이 스크립트를 실행하면,
패키지의 핵심 구조를 자동으로 docs/latest_syntax.md에 추가합니다.

사용법:
    python scripts/scan_packages.py openai pydantic litellm
    python scripts/scan_packages.py --all  # 모니터링 대상 전체 스캔

Learning Loop의 '능동형 업데이트(Install-Time Scan)' 부분입니다.
"""

import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.knowledge_updater import scan_and_save, scan_package
from utils.introspector import MONITORED_PACKAGES, get_package_version


def main():
    if len(sys.argv) < 2:
        print("사용법: python scripts/scan_packages.py <package1> [package2] ...")
        print("        python scripts/scan_packages.py --all")
        print(f"\n모니터링 대상: {', '.join(MONITORED_PACKAGES)}")
        sys.exit(1)

    # --all 옵션: 모니터링 대상 전체 스캔
    if sys.argv[1] == "--all":
        packages = MONITORED_PACKAGES
    else:
        packages = sys.argv[1:]

    print("=" * 50)
    print("📦 Package Scanner — 자동 매뉴얼 생성")
    print("=" * 50)

    success_count = 0
    for pkg in packages:
        version = get_package_version(pkg)
        if version is None:
            print(f"  ⚠️  {pkg}: 설치되지 않음 → 스킵")
            continue

        print(f"  🔍 {pkg} v{version} 스캔 중...")

        # 미리보기 출력
        summary = scan_package(pkg)
        if summary:
            preview = summary[:200].replace("\n", "\n     ")
            print(f"     {preview}...")

        if scan_and_save(pkg):
            print(f"  ✅ {pkg} → docs/latest_syntax.md 에 추가됨")
            success_count += 1
        else:
            print(f"  ❌ {pkg} 스캔 실패")

    print()
    print(f"완료: {success_count}/{len(packages)}개 패키지 스캔 성공")
    print(f"📄 결과 파일: docs/latest_syntax.md")


if __name__ == "__main__":
    main()
