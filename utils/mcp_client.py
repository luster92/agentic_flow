"""
MCP Client Module
=================
Model Context Protocol (MCP) Client Implementation.
Connects to local MCP servers via stdio and exposes their tools.
"""

import asyncio
import os
import logging
import shutil
import json
from contextlib import AsyncExitStack

# Using standard mcp library imports (assuming mcp-python-sdk structure)
# If actual library differs, this might need adjustment, but standard is:
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from utils.tools import BaseTool

logger = logging.getLogger(__name__)

class MCPTool(BaseTool):
    """
    Adapter for MCP Tools to be used as Agent Tools.
    """
    def __init__(self, name: str, description: str, parameters: dict, session: ClientSession, server_name: str):
        self._name = name
        self._description = description
        self._parameters = parameters
        self._session = session
        self._server_name = server_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        # OpenAI requires description.
        return self._description or f"Tool provided by {self._server_name}"

    @property
    def parameters(self) -> dict:
        return self._parameters

    async def execute(self, **kwargs) -> str:
        """
        Execute the tool via MCP session.
        """
        try:
            # mcp call_tool returns a Result object with 'content' list
            result = await self._session.call_tool(self.name, arguments=kwargs)
            
            # Combine content blocks (TextContent, ImageContent, etc.)
            output = []
            if hasattr(result, 'content'):
                for block in result.content:
                    if hasattr(block, 'text'):
                        output.append(block.text)
                    else:
                        output.append(str(block))
            return "\n".join(output)
            
        except Exception as e:
            return f"❌ MCP Tool Error ({self.name}): {str(e)}"

class MCPManager:
    """
    Manages connections to multiple MCP servers.
    """
    
    def __init__(self):
        self.exit_stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}

    async def connect_server(self, name: str, command: str, args: list[str], env: dict | None = None) -> bool:
        """
        Connects to a local MCP server via stdio.
        """
        try:
            # Resolve command path
            cmd_path = shutil.which(command)
            if not cmd_path:
                logger.error(f"❌ MCP Server '{name}': Command not found: {command}")
                return False

            server_env = os.environ.copy()
            if env:
                server_env.update(env)

            # Create server parameters
            params = StdioServerParameters(
                command=command,
                args=args,
                env=server_env
            )
            
            # Start connection using exit_stack to manage context
            logger.info(f"🔌 Connecting to MCP Server: {name}...")
            
            # Enter contexts
            read, write = await self.exit_stack.enter_async_context(stdio_client(params))
            session = await self.exit_stack.enter_async_context(ClientSession(read, write))
            
            # Initialize handshake
            await session.initialize()
            
            self.sessions[name] = session
            logger.info(f"✅ Connected to MCP Server: {name}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to connect to MCP Server '{name}': {e}")
            return False

    async def get_tools(self) -> list[BaseTool]:
        """
        Fetch tools from all connected servers.
        """
        all_tools = []
        for name, session in self.sessions.items():
            try:
                result = await session.list_tools()
                for tool in result.tools:
                    wrapper = MCPTool(
                        name=tool.name,
                        description=tool.description,
                        parameters=tool.inputSchema,
                        session=session,
                        server_name=name
                    )
                    all_tools.append(wrapper)
                    logger.debug(f"  └─ Discovered MCP Tool: {tool.name}")
                    
            except Exception as e:
                logger.error(f"⚠️ Failed to list tools from '{name}': {e}")
                
        return all_tools

    async def cleanup(self):
        """Close all connections."""
        await self.exit_stack.aclose()
        self.sessions.clear()
        logger.info("🔌 MCP Connections closed.")

# Global Manager Instance
global_mcp_manager = MCPManager()
