import subprocess
import logging
import asyncio

logger = logging.getLogger("terminal_engine")

class TerminalEngine:
    """터미널 상호작용 및 로컬 환경 프로세스를 관리합니다."""
    
    @staticmethod
    async def execute_command(command: str) -> str:
        """'!' 접두어로 시작하는 터미널 명령어를 즉시 실행하고 stdout을 캡처합니다."""
        
        # Remove the leading '!' if present
        if command.startswith("!"):
            cmd = command[1:].strip()
        else:
            cmd = command.strip()
            
        logger.info(f"💻 [Terminal] Executing immediate command: {cmd}")
        
        try:
            # We use asyncio.create_subprocess_shell to keep it non-blocking
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout_data, stderr_data = await process.communicate()
            
            output = ""
            if stdout_data:
                output += stdout_data.decode("utf-8").strip()
            if stderr_data:
                if output:
                    output += "\n"
                output += stderr_data.decode("utf-8").strip()
                
            if process.returncode != 0:
                output = f"[Exit Code: {process.returncode}]\n{output}"
                
            return output if output else "[No output from command]"
            
        except Exception as e:
            logger.error(f"❌ Failed to execute command '{cmd}': {e}")
            return f"[ERROR] Execution failed: {e}"

    @staticmethod
    def get_context_profiler_stats(history: dict, mcp_tools: list) -> str:
        """현재 컨텍스트의 토큰 분석(어림짐작)을 시각화합니다."""
        # Simple heuristic character-based token estimates (approx 4 chars/token)
        sys_prompt_len = sum(len(m.get("content", "")) for m in history if m.get("role") == "system")
        history_len = sum(len(m.get("content", "")) for m in history if m.get("role") in ["user", "assistant"])
        
        sys_tokens = sys_prompt_len // 4
        hist_tokens = history_len // 4
        mcp_tokens = len(str(mcp_tools)) // 4
        
        total = sys_tokens + hist_tokens + mcp_tokens
        if total == 0:
            total = 1
            
        stats = (
            f"\n📊 [Context Profiler]\n"
            f"   Total Estimated Tokens: ~{total}\n"
            f"   ├─ System Prompts & Logic: ~{sys_tokens} ({sys_tokens/total*100:.1f}%)\n"
            f"   ├─ Conversation History: ~{hist_tokens} ({hist_tokens/total*100:.1f}%)\n"
            f"   └─ MCP Tools Payload: ~{mcp_tokens} ({mcp_tokens/total*100:.1f}%)\n"
        )
        return stats
