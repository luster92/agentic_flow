import asyncio
import logging
from typing import Optional

logger = logging.getLogger("tmux_integration")

class TmuxIntegration:
    """백그라운드에서 자율 검증(Write-Test Cycle)을 실행하기 위한 tmux 멀티플렉서 연동 모듈입니다."""
    
    @staticmethod
    async def create_session(session_name: str) -> bool:
        """새로운 tmux 세션을 백그라운드에 생성합니다."""
        cmd = f"tmux has-session -t {session_name} 2>/dev/null || tmux new-session -d -s {session_name}"
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return proc.returncode == 0

    @staticmethod
    async def run_test(session_name: str, test_command: str) -> None:
        """세션에 명령어를 인젝션합니다."""
        logger.info(f"🧪 Injecting test command into tmux {session_name}: {test_command}")
        cmd = f"tmux send-keys -t {session_name} '{test_command}' C-m"
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

    @staticmethod
    async def get_test_output(session_name: str, capture_lines: int = 100) -> str:
        """tmux 패널 버퍼를 캡처하여 터미널 출력을 가져옵니다."""
        logger.info(f"📸 Capturing tmux pane from {session_name}")
        cmd = f"tmux capture-pane -p -t {session_name} -S -{capture_lines}"
        
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0:
            return stdout.decode('utf-8').strip()
        else:
            logger.error(f"❌ Failed to capture tmux pane: {stderr.decode()}")
            return f"[ERROR] Tmux capture failed: {stderr.decode()}"

    @staticmethod
    async def kill_session(session_name: str) -> None:
        """tmux 세션을 종료합니다."""
        cmd = f"tmux kill-session -t {session_name}"
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        logger.info(f"🗑️ Destroyed tmux session: {session_name}")
