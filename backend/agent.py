"""
LangGraph agent with Arcade MCP tools.

Uses langchain-mcp-adapters to connect to Arcade's MCP gateway,
which provides SharePoint, Outlook, Teams, and other Microsoft tools.

The graph factory pattern accepts a `runtime` parameter from LangGraph,
which contains the authenticated user's info for user-scoped OAuth.
"""

from langchain.agents import create_agent
from langgraph.runtime import Runtime

# Import Arcade MCP tools helper
from backend.arcade_tools import get_arcade_tools


async def create_arcade_agent(runtime: Runtime):
    """
    Create an agent with Arcade tools loaded via MCP.
    
    This is a graph factory function - LangGraph passes the runtime parameter
    which contains configurable settings including the authenticated user info.
    
    Args:
        runtime: Runtime object passed by LangGraph, contains auth user info
    
    Returns:
        Compiled agent graph with Arcade tools
    """
    print(f"🚀 create_arcade_agent called with runtime: {type(runtime)}")
    
    # Get Arcade tools - passes runtime to extract user_id for OAuth scoping
    tools = await get_arcade_tools(runtime)
    
    agent = create_agent(
        model="openai:gpt-4o",
        tools=tools,
        system_prompt="You're a helpful assistant."
    )
    
    print(f"✅ Agent created with {len(tools)} tools")
    return agent
