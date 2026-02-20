import os
import asyncio
import logging
from typing import Optional

logger = logging.getLogger("sandbox")

class SandboxManager:
    """도커 기반의 격리된 실행 환경(Safeclaw)을 프로비저닝하여, 호스트 머신을 보호합니다."""
    
    def __init__(self, base_image: str = "python:3.11-slim"):
        self.base_image = base_image

    async def provision_container(self, session_id: str) -> Optional[str]:
        """해당 세션에 대한 고유한 샌드박스 컨테이너를 구동합니다."""
        container_name = f"safeclaw-{session_id}"
        
        # Check if already running
        check_cmd = f"docker ps -q -f name={container_name}"
        proc = await asyncio.create_subprocess_shell(
            check_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if stdout.strip():
            logger.info(f"🐳 Sandbox already running: {container_name}")
            return container_name
            
        logger.info(f"🐳 Provisioning Safeclaw sandbox: {container_name}")
        cmd = (
            f"docker run -d --rm --name {container_name} "
            f"--network bridge "
            f"{self.base_image} tail -f /dev/null"
        )
        
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0:
            logger.info(f"✅ Safeclaw started: {container_name}")
            return container_name
        else:
            logger.error(f"❌ Failed to start Safeclaw: {stderr.decode()}")
            return None

    async def execute_in_sandbox(self, session_id: str, command: str) -> str:
        """컨테이너 내부에서 명령어를 실행하고 결과를 반환합니다."""
        container_name = f"safeclaw-{session_id}"
        
        cmd = f"docker exec {container_name} sh -c '{command}'"
        logger.info(f"🛡️ Executing in Safeclaw sandbox: {cmd}")
        
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        out = stdout.decode('utf-8').strip() if stdout else ""
        err = stderr.decode('utf-8').strip() if stderr else ""
        
        if proc.returncode != 0:
            return f"[Exit Code: {proc.returncode}]\n{err}\n{out}"
        return out if out else "[Command executed with no output]"

    async def teardown_container(self, session_id: str) -> None:
        """세션 종료 시 샌드박스 컨테이너를 삭제합니다."""
        container_name = f"safeclaw-{session_id}"
        cmd = f"docker stop {container_name}"
        logger.info(f"🗑️ Tearing down Safeclaw sandbox: {container_name}")
        
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
