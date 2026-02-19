#!/bin/bash
# ============================================================
# AgenticFlow — Apple Silicon M4 환경 최적화 설치 스크립트
# ============================================================
# Mac Mini M4 (32GB)에서 OpenClaw + AgenticFlow를 구동하기 위한
# 원클릭 설치 스크립트입니다.
#
# Usage:
#   bash setup_m4.sh                   # 기본 설치
#   bash setup_m4.sh --apply-sysctl    # GPU 메모리 한도 조정 포함
#   bash setup_m4.sh --skip-model      # 모델 다운로드 생략
#   bash setup_m4.sh --help            # 사용법
# ============================================================

set -euo pipefail

# ── 색상 정의 ──────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ── 옵션 파싱 ──────────────────────────────────────────────────
APPLY_SYSCTL=false
SKIP_MODEL=false

usage() {
    echo -e "${CYAN}AgenticFlow M4 Setup${NC}"
    echo ""
    echo "Usage: bash setup_m4.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --apply-sysctl   GPU wired memory 한도를 26GB로 상향 (sudo 필요)"
    echo "  --skip-model     모델 다운로드를 건너뜀"
    echo "  --help           이 도움말 출력"
    echo ""
    echo "Requirements:"
    echo "  - Apple Silicon Mac (M1/M2/M3/M4)"
    echo "  - Python 3.11+"
    echo "  - 32GB+ RAM 권장"
}

for arg in "$@"; do
    case $arg in
        --apply-sysctl)
            APPLY_SYSCTL=true
            shift
            ;;
        --skip-model)
            SKIP_MODEL=true
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            echo -e "${RED}알 수 없는 옵션: $arg${NC}"
            usage
            exit 1
            ;;
    esac
done

# ── 배너 ──────────────────────────────────────────────────────
echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║     🚀 AgenticFlow — Apple Silicon M4 Setup            ║"
echo "║     OpenClaw Integration + MLX Optimization            ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. 하드웨어 검증 ──────────────────────────────────────────
echo -e "${BLUE}[1/6] 하드웨어 검증 중...${NC}"

ARCH=$(uname -m)
if [ "$ARCH" != "arm64" ]; then
    echo -e "${RED}❌ 오류: 이 스크립트는 Apple Silicon(arm64) 전용입니다.${NC}"
    echo -e "   현재 아키텍처: $ARCH"
    exit 1
fi

if [ "$(uname -s)" != "Darwin" ]; then
    echo -e "${RED}❌ 오류: macOS에서만 실행 가능합니다.${NC}"
    exit 1
fi

CHIP=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "Unknown")
MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
MEM_GB=$((MEM_BYTES / 1073741824))

echo -e "${GREEN}  ✅ 칩: $CHIP${NC}"
echo -e "${GREEN}  ✅ 메모리: ${MEM_GB}GB${NC}"
echo -e "${GREEN}  ✅ 아키텍처: $ARCH${NC}"

if [ "$MEM_GB" -lt 16 ]; then
    echo -e "${YELLOW}  ⚠️ 경고: 16GB 미만 메모리에서는 32B 모델 사용이 불가합니다.${NC}"
    echo -e "  14B 또는 7B 모델을 사용하세요."
fi

# ── 2. Python 환경 확인 ───────────────────────────────────────
echo ""
echo -e "${BLUE}[2/6] Python 환경 확인 중...${NC}"

PYTHON_VERSION=$(python3 --version 2>/dev/null || echo "not found")
echo -e "  Python: $PYTHON_VERSION"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3가 설치되어 있지 않습니다.${NC}"
    echo "  brew install python3"
    exit 1
fi

# ── 3. 가상환경 생성 ──────────────────────────────────────────
echo ""
echo -e "${BLUE}[3/6] 가상환경 설정 중...${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo -e "  가상환경 생성 중: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}  ✅ 가상환경 생성 완료${NC}"
else
    echo -e "${GREEN}  ✅ 기존 가상환경 사용${NC}"
fi

source "$VENV_DIR/bin/activate"

# ── 4. 의존성 설치 ────────────────────────────────────────────
echo ""
echo -e "${BLUE}[4/6] 의존성 설치 중...${NC}"

# pip 업그레이드
pip install --upgrade pip -q

# 기본 의존성
echo -e "  기본 패키지 설치 중..."
pip install -r "$SCRIPT_DIR/requirements.txt" -q

# Apple Silicon 전용 패키지
echo -e "  Apple Silicon 전용 패키지 설치 중..."
pip install mlx mlx-lm fastmcp psutil huggingface_hub -q

echo -e "${GREEN}  ✅ 모든 의존성 설치 완료${NC}"

# ── 5. sysctl 설정 (선택적) ───────────────────────────────────
echo ""
echo -e "${BLUE}[5/6] 시스템 최적화...${NC}"

if [ "$APPLY_SYSCTL" = true ]; then
    if [ "$MEM_GB" -ge 128 ]; then
        WIRED_LIMIT=110592 # 108GB for 128GB systems
    elif [ "$MEM_GB" -ge 64 ]; then
        WIRED_LIMIT=53248  # 52GB for 64GB systems
    elif [ "$MEM_GB" -ge 32 ]; then
        WIRED_LIMIT=26624  # 26GB for 32GB systems
    elif [ "$MEM_GB" -ge 16 ]; then
        WIRED_LIMIT=12288  # 12GB for 16GB systems
    else
        WIRED_LIMIT=6144   # 6GB for 8GB systems
    fi

    echo -e "  GPU Wired Memory 한도를 ${WIRED_LIMIT}MB로 설정합니다..."
    echo -e "${YELLOW}  ⚠️ sudo 비밀번호가 필요합니다.${NC}"
    sudo sysctl iogpu.wired_limit_mb=$WIRED_LIMIT
    echo -e "${GREEN}  ✅ iogpu.wired_limit_mb = $WIRED_LIMIT${NC}"
else
    echo -e "  ℹ️ sysctl 설정 건너뜀 (--apply-sysctl 옵션으로 활성화)"
fi

# ── 6. 모델 다운로드 (선택적) ─────────────────────────────────
echo ""
echo -e "${BLUE}[6/6] 모델 준비...${NC}"

if [ "$SKIP_MODEL" = true ]; then
    echo -e "  ℹ️ 모델 다운로드 건너뜀 (--skip-model)"
else
    echo -e "  모델은 첫 실행 시 자동으로 다운로드됩니다."
    echo -e "  수동 다운로드: python -c \"from mlx_lm import load; load('mlx-community/Qwen2.5-32B-Instruct-4bit')\""
fi

# ── 완료 ──────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║     ✅ 설치 완료!                                       ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║  실행 방법:                                              ║"
echo "║    source .venv/bin/activate                             ║"
echo "║                                                          ║"
echo "║  CLI 모드:                                               ║"
echo "║    python main.py                                        ║"
echo "║                                                          ║"
echo "║  MCP 서버 (OpenClaw 연동):                               ║"
echo "║    python server.py                                      ║"
echo "║    python server.py --transport sse --port 8765           ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"
