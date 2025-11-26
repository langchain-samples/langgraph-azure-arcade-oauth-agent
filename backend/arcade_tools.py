"""
Arcade.dev tool integration for LangGraph agent using MCP Adapters.

This module connects to Arcade's MCP gateway using langchain-mcp-adapters,
which provides a cleaner integration than wrapping tools manually.

Flow:
1. User authenticates via Azure AD → LangGraph stores user_id in langgraph_auth_user
2. MCP client connects to Arcade with user_id in headers
3. Arcade routes requests to appropriate MCP servers (SharePoint, etc.)
4. If OAuth needed → tool returns auth_url for user to complete
5. After OAuth completes → /arcade/verify confirms user identity
6. Subsequent calls use cached OAuth token automatically

Reference: https://docs.arcade.dev/en/home/auth/secure-auth-production
"""

import os
from langgraph.runtime import Runtime
from langchain_mcp_adapters.client import MultiServerMCPClient


# Arcade MCP Gateway URL
ARCADE_MCP_URL = os.environ.get("ARCADE_MCP_URL", "https://api.arcade.dev/v1/mcp")
ARCADE_API_KEY = os.environ.get("ARCADE_API_KEY")


def get_user_id_from_runtime(runtime: Runtime) -> str:
    """
    Extract the authenticated user's ID from LangGraph runtime.
    
    The runtime is passed as a parameter to graph factory functions by LangGraph.
    It's dict-like and contains the configurable params including auth user info
    populated by @auth.authenticate middleware.
    
    Args:
        runtime: Runtime object passed to graph factory functions
        
    Returns:
        The user's identity string (oid.tid format from Azure AD)
    """
    configurable = runtime.get("configurable", {})
    user = configurable.get("langgraph_auth_user", {})
    user_id = user.get("identity")
    
    if not user_id:
        raise ValueError("No authenticated user found in runtime context")
    return user_id


def get_arcade_mcp_client(user_id: str):
    """
    Create an MCP client configured for Arcade with user-scoped headers.
    
    The client connects to Arcade's MCP gateway and passes:
    - Authorization: Bearer <ARCADE_API_KEY>
    - Arcade-User-Id: <user_id from Azure AD>
    
    This ensures OAuth tokens are scoped to the correct user.
    
    Args:
        user_id: The authenticated user's identity from Azure AD
    """
    return MultiServerMCPClient({
        "arcade": {
            "transport": "streamable_http",
            "url": ARCADE_MCP_URL,
            "headers": {
                "Authorization": f"Bearer {ARCADE_API_KEY}",
                "Arcade-User-Id": user_id,
            }
        }
    })


async def get_arcade_tools(runtime: Runtime):
    """
    Get Arcade tools via MCP adapter.
    
    This connects to Arcade's MCP gateway and retrieves all available tools
    (SharePoint, Outlook, Teams, etc.) as LangChain-compatible tools.
    
    The user_id is extracted from the runtime and passed in headers 
    so Arcade knows which user's OAuth tokens to use for each tool call.
    
    Args:
        runtime: Runtime object passed to graph factory functions by LangGraph
    
    Returns:
        List of LangChain-compatible tools from Arcade MCP servers
    
    Usage in graph factory:
        async def make_graph(runtime: Runtime):
            tools = await get_arcade_tools(runtime)
            return create_agent(model="gpt-4o", tools=tools)
    """
    user_id = get_user_id_from_runtime(runtime)
    client = get_arcade_mcp_client(user_id)
    return await client.get_tools()


__all__ = ["get_arcade_tools", "get_user_id_from_runtime", "get_arcade_mcp_client"]
