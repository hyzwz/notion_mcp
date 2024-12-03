from mcp.server import Server
from mcp.types import (
    Resource, 
    Tool,
    TextContent,
    EmbeddedResource
)
from pydantic import AnyUrl
import os
import json
from datetime import datetime
import httpx
from typing import Any, Sequence
from dotenv import load_dotenv
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('notion_mcp')

# Find and load .env file from project root
project_root = Path(__file__).parent.parent.parent
env_path = project_root / '.env'
if not env_path.exists():
    raise FileNotFoundError(f"No .env file found at {env_path}")
load_dotenv(env_path)

# Initialize server
server = Server("notion-todo")

# Configuration with validation
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_API_KEY:
    raise ValueError("NOTION_API_KEY not found in .env file")
if not DATABASE_ID:
    raise ValueError("NOTION_DATABASE_ID not found in .env file")

NOTION_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

# Notion API headers
headers = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION
}

async def fetch_todos(
    status: str = None,
    assignee: str = None,
    priority: str = None,
    project: str = None,
    sprint: str = None,
    sort_by: str = "Due",
    sort_direction: str = "ascending"
) -> dict:
    """Fetch todos from Notion database with filters
    
    Args:
        status: Filter by status (Done, In progress, Not started)
        assignee: Filter by assignee
        priority: Filter by priority (High, Medium, Low)
        project: Filter by project
        sprint: Filter by sprint
        sort_by: Field to sort by
        sort_direction: Sort direction (ascending or descending)
    """
    filter_conditions = []
    
    if status:
        filter_conditions.append({
            "property": "Status",
            "select": {"equals": status}
        })
    
    if assignee:
        filter_conditions.append({
            "property": "Assignee",
            "people": {"contains": assignee}
        })
    
    if priority:
        filter_conditions.append({
            "property": "Priority",
            "select": {"equals": priority}
        })
    
    if project:
        filter_conditions.append({
            "property": "Project",
            "select": {"equals": project}
        })
    
    if sprint:
        filter_conditions.append({
            "property": "Sprint",
            "select": {"equals": sprint}
        })
    
    filter_obj = {}
    if filter_conditions:
        filter_obj["filter"] = {
            "and": filter_conditions
        }
    
    filter_obj["sorts"] = [{
        "property": sort_by,
        "direction": sort_direction
    }]

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{NOTION_BASE_URL}/databases/{DATABASE_ID}/query",
            headers=headers,
            json=filter_obj
        )
        response.raise_for_status()
        return response.json()

async def create_todo(
    task: str,
    assignee: str = "",
    due_date: str = "",
    priority: str = "Medium",
    tags: list[str] = None,
    sprint: str = "",
    project: str = "",
    status: str = "Not started"
) -> dict:
    """Create a new todo in Notion
    
    Args:
        task: Task name
        assignee: Task assignee
        due_date: Due date in YYYY-MM-DD format
        priority: Task priority (High, Medium, Low)
        tags: List of tags
        sprint: Sprint name
        project: Project name
        status: Task status (Done, In progress, Not started)
    """
    properties = {
        "Task name": {
            "type": "title",
            "title": [{"type": "text", "text": {"content": task}}]
        },
        "Status": {
            "type": "select",
            "select": {"name": status}
        }
    }
    
    if assignee:
        properties["Assignee"] = {
            "type": "people",
            "people": [{"id": assignee}]
        }
    
    if due_date:
        properties["Due"] = {
            "type": "date",
            "date": {"start": due_date}
        }
    
    if priority:
        properties["Priority"] = {
            "type": "select",
            "select": {"name": priority}
        }
    
    if tags:
        properties["Tags"] = {
            "type": "multi_select",
            "multi_select": [{"name": tag} for tag in tags]
        }
    
    if sprint:
        properties["Sprint"] = {
            "type": "select",
            "select": {"name": sprint}
        }
        
    if project:
        properties["Project"] = {
            "type": "select",
            "select": {"name": project}
        }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{NOTION_BASE_URL}/pages",
            headers=headers,
            json={
                "parent": {"database_id": DATABASE_ID},
                "properties": properties
            }
        )
        response.raise_for_status()
        return response.json()

async def complete_todo(page_id: str) -> dict:
    """Mark a todo as complete in Notion"""
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{NOTION_BASE_URL}/pages/{page_id}",
            headers=headers,
            json={
                "properties": {
                    "Checkbox": {
                        "type": "checkbox",
                        "checkbox": True
                    }
                }
            }
        )
        response.raise_for_status()
        return response.json()

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available todo tools"""
    return [
        Tool(
            name="add_todo",
            description="Add a new todo item",
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The todo task description"
                    },
                    "when": {
                        "type": "string",
                        "description": "When the task should be done (today or later)",
                        "enum": ["today", "later"]
                    }
                },
                "required": ["task", "when"]
            }
        ),
        Tool(
            name="show_all_todos",
            description="Show all todo items from Notion",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="show_today_todos",
            description="Show today's todo items from Notion",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="complete_todo",
            description="Mark a todo item as complete",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The ID of the todo task to mark as complete"
                    }
                },
                "required": ["task_id"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent | EmbeddedResource]:
    """Handle tool calls for todo management"""
    if name == "add_todo":
        if not isinstance(arguments, dict):
            raise ValueError("Invalid arguments")
            
        task = arguments.get("task")
        when = arguments.get("when", "later")
        
        if not task:
            raise ValueError("Task is required")
        if when not in ["today", "later"]:
            raise ValueError("When must be 'today' or 'later'")
            
        try:
            result = await create_todo(task, when=when)
            return [
                TextContent(
                    type="text",
                    text=f"Added todo: {task} (scheduled for {when})"
                )
            ]
        except httpx.HTTPError as e:
            logger.error(f"Notion API error: {str(e)}")
            return [
                TextContent(
                    type="text",
                    text=f"Error adding todo: {str(e)}\nPlease make sure your Notion integration is properly set up and has access to the database."
                )
            ]
            
    elif name in ["show_all_todos", "show_today_todos"]:
        try:
            todos = await fetch_todos()
            formatted_todos = []
            for todo in todos.get("results", []):
                props = todo["properties"]
                formatted_todo = {
                    "id": todo["id"],  # Include the page ID in the response
                    "task": props["Task"]["title"][0]["text"]["content"] if props["Task"]["title"] else "",
                    "completed": props["Checkbox"]["checkbox"],
                    "when": props["When"]["select"]["name"] if props["When"]["select"] else "unknown",
                    "created": todo["created_time"]
                }
                
                if name == "show_today_todos" and formatted_todo["when"].lower() != "today":
                    continue
                    
                formatted_todos.append(formatted_todo)
            
            return [
                TextContent(
                    type="text",
                    text=json.dumps(formatted_todos, indent=2)
                )
            ]
        except httpx.HTTPError as e:
            logger.error(f"Notion API error: {str(e)}")
            return [
                TextContent(
                    type="text",
                    text=f"Error fetching todos: {str(e)}\nPlease make sure your Notion integration is properly set up and has access to the database."
                )
            ]
    
    elif name == "complete_todo":
        if not isinstance(arguments, dict):
            raise ValueError("Invalid arguments")
            
        task_id = arguments.get("task_id")
        if not task_id:
            raise ValueError("Task ID is required")
            
        try:
            result = await complete_todo(task_id)
            return [
                TextContent(
                    type="text",
                    text=f"Marked todo as complete (ID: {task_id})"
                )
            ]
        except httpx.HTTPError as e:
            logger.error(f"Notion API error: {str(e)}")
            return [
                TextContent(
                    type="text",
                    text=f"Error completing todo: {str(e)}\nPlease make sure your Notion integration is properly set up and has access to the database."
                )
            ]
    
    raise ValueError(f"Unknown tool: {name}")

async def main():
    """Main entry point for the server"""
    from mcp.server.stdio import stdio_server
    
    if not NOTION_API_KEY or not DATABASE_ID:
        raise ValueError("NOTION_API_KEY and NOTION_DATABASE_ID environment variables are required")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())