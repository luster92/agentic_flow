#!/bin/bash
# ============================================================
# AgenticFlow — OpenClaw 스킬 설치 헬퍼
# ============================================================
# OpenClaw의 스킬 디렉토리에 AgenticFlow를 등록합니다.
#
# Usage:
#   bash install_skill.sh                  # 기본 설치
#   bash install_skill.sh --openclaw-dir   # 커스텀 경로
# ============================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTIC_FLOW_DIR="$(dirname "$SCRIPT_DIR")"
OPENCLAW_DIR="${OPENCLAW_DIR:-$HOME/.openclaw}"
SKILLS_DIR="$OPENCLAW_DIR/skills"

echo -e "${CYAN}🔗 AgenticFlow → OpenClaw 스킬 설치${NC}"
echo ""

# ── OpenClaw 디렉토리 확인 ────────────────────────────────────
if [ ! -d "$OPENCLAW_DIR" ]; then
    echo -e "${YELLOW}⚠️ OpenClaw 디렉토리가 없습니다: $OPENCLAW_DIR${NC}"
    echo -e "  생성합니다..."
    mkdir -p "$OPENCLAW_DIR"
    mkdir -p "$SKILLS_DIR"
fi

if [ ! -d "$SKILLS_DIR" ]; then
    mkdir -p "$SKILLS_DIR"
fi

# ── 심링크 생성 ───────────────────────────────────────────────
SKILL_LINK="$SKILLS_DIR/agentic_flow"

if [ -L "$SKILL_LINK" ]; then
    echo -e "  기존 심링크 제거 중..."
    rm "$SKILL_LINK"
fi

ln -s "$AGENTIC_FLOW_DIR" "$SKILL_LINK"
echo -e "${GREEN}✅ 심링크 생성: $SKILL_LINK → $AGENTIC_FLOW_DIR${NC}"

# ── SOUL.md 생성 (없으면) ─────────────────────────────────────
SOUL_FILE="$OPENCLAW_DIR/SOUL.md"

if [ ! -f "$SOUL_FILE" ]; then
    echo -e "  SOUL.md 템플릿 생성 중..."
    cat > "$SOUL_FILE" << 'EOF'
# Personality
친절하고 전문적인 시니어 소프트웨어 엔지니어.
복잡한 문제를 체계적으로 분석하고 실용적인 솔루션을 제시합니다.

# Tone
- 존댓말 사용
- 기술 용어는 한국어 우선, 필요 시 영어 병기
- 코드 예시 적극 활용

# Principles
1. 정확성이 최우선: 불확실하면 "모르겠다"고 솔직하게 답변
2. 보안을 항상 고려: API 키, 비밀번호 등 민감 정보 노출 금지
3. 효율성 추구: 불필요한 연산이나 API 호출 최소화
4. 테스트 가능한 코드: 모든 코드는 테스트를 포함

# Constraints
- 시스템 파일 (/etc, /System) 수정 금지
- rm -rf 등 위험 명령어 사전 확인
- 32GB 메모리 한도 내에서 작업
EOF
    echo -e "${GREEN}✅ SOUL.md 생성: $SOUL_FILE${NC}"
else
    echo -e "  ℹ️ SOUL.md 이미 존재: $SOUL_FILE"
fi

# ── MEMORY.md 생성 (없으면) ───────────────────────────────────
MEMORY_FILE="$OPENCLAW_DIR/MEMORY.md"

if [ ! -f "$MEMORY_FILE" ]; then
    echo -e "  MEMORY.md 템플릿 생성 중..."
    cat > "$MEMORY_FILE" << 'EOF'
## $(date +%Y-%m-%d)
- **setup**: AgenticFlow OpenClaw 스킬 설치 완료
EOF
    echo -e "${GREEN}✅ MEMORY.md 생성: $MEMORY_FILE${NC}"
else
    echo -e "  ℹ️ MEMORY.md 이미 존재: $MEMORY_FILE"
fi

# ── 완료 ──────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}✅ 스킬 설치 완료!${NC}"
echo ""
echo -e "  스킬 경로: $SKILL_LINK"
echo -e "  SOUL: $SOUL_FILE"
echo -e "  MEMORY: $MEMORY_FILE"
echo ""
echo -e "  OpenClaw에서 사용: \"심층 분석\", \"코드 리팩토링\" 등의 트리거 사용"
