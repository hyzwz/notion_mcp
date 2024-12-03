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
from datetime import datetime, timezone, date
from typing import Any, Sequence, Optional, Dict, List, Union
import httpx
from dotenv import load_dotenv
from pathlib import Path
import logging

# Set up logging with more detailed format
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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

class NotionJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for Notion API responses"""
    def default(self, obj):
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        if isinstance(obj, (Resource, Tool, TextContent, EmbeddedResource)):
            return str(obj)
        return super().default(obj)

def safe_json_dumps(obj: Any) -> str:
    """Safely convert object to JSON string"""
    return json.dumps(obj, cls=NotionJSONEncoder, ensure_ascii=False)

def validate_date(date_str: str) -> bool:
    """Validate date string format (YYYY-MM-DD)"""
    try:
        if not date_str:
            return True
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False

def safe_get_property(properties: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Safely get property from Notion properties object"""
    try:
        prop = properties.get(key, {})
        prop_type = prop.get("type")
        
        if not prop or not prop_type:
            return default
            
        if prop_type == "title":
            return prop["title"][0]["text"]["content"] if prop["title"] else default
        elif prop_type == "select":
            return prop["select"]["name"] if prop["select"] else default
        elif prop_type == "multi_select":
            return [item["name"] for item in prop["multi_select"]] if prop["multi_select"] else default
        elif prop_type == "date":
            return prop["date"]["start"] if prop["date"] else default
        elif prop_type == "people":
            return [person["name"] for person in prop["people"]] if prop["people"] else default
        elif prop_type == "relation":
            return [rel["id"] for rel in prop["relation"]] if prop["relation"] else default
        else:
            return default
    except Exception as e:
        logger.error(f"Error getting property {key}: {str(e)}")
        return default

async def fetch_todos(
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    priority: Optional[str] = None,
    project: Optional[str] = None,
    sprint: Optional[str] = None,
    sort_by: str = "Due",
    sort_direction: str = "ascending"
) -> dict:
    """Fetch todos from Notion database with filters"""
    try:
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
                "relation": {"contains": project}
            })
        
        if sprint:
            filter_conditions.append({
                "property": "Sprint",
                "relation": {"contains": sprint}
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

        logger.debug(f"Querying Notion with filters: {safe_json_dumps(filter_obj)}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{NOTION_BASE_URL}/databases/{DATABASE_ID}/query",
                headers=headers,
                json=filter_obj,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Received {len(data.get('results', []))} todos from Notion")
            return data
            
    except httpx.TimeoutException:
        logger.error("Request to Notion API timed out")
        raise
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in fetch_todos: {str(e)}")
        raise

async def create_todo(
    task: str,
    assignee: str = "",
    due: str = "",
    priority: str = "Medium",
    tags: Optional[List[str]] = None,
    sprint: str = "",
    project: str = "",
    status: str = "Not started",
    github_pr: str = ""
) -> dict:
    """Create a new todo in Notion"""
    try:
        if not task:
            raise ValueError("Task name is required")
            
        if not validate_date(due):
            raise ValueError("Invalid date format. Use YYYY-MM-DD")
            
        if priority not in ["High", "Medium", "Low"]:
            raise ValueError("Invalid priority. Must be High, Medium, or Low")
            
        if status not in ["Done", "In progress", "Not started"]:
            raise ValueError("Invalid status. Must be Done, In progress, or Not started")

        properties = {
            "Task name": {
                "type": "title",
                "title": [{"type": "text", "text": {"content": task}}]
            },
            "Status": {
                "type": "select",
                "select": {"name": status}
            },
            "Priority": {
                "type": "select",
                "select": {"name": priority}
            }
        }

        if due:
            properties["Due"] = {
                "type": "date",
                "date": {"start": due}
            }

        if assignee:
            properties["Assignee"] = {
                "type": "people",
                "people": [{"object": "user", "id": assignee}]
            }

        if tags:
            properties["Tags"] = {
                "type": "multi_select",
                "multi_select": [{"name": tag} for tag in tags]
            }

        if sprint:
            properties["Sprint"] = {
                "type": "relation",
                "relation": [{"id": sprint}]
            }

        if project:
            properties["Project"] = {
                "type": "relation",
                "relation": [{"id": project}]
            }

        if github_pr:
            properties["GitHub PR"] = {
                "type": "url",
                "url": github_pr
            }

        logger.debug(f"Creating todo with properties: {safe_json_dumps(properties)}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{NOTION_BASE_URL}/pages",
                headers=headers,
                json={
                    "parent": {"database_id": DATABASE_ID},
                    "properties": properties
                },
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            logger.info(f"Created todo: {task}")
            return data

    except httpx.TimeoutException:
        logger.error("Request to Notion API timed out")
        raise
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {str(e)}")
        raise
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in create_todo: {str(e)}")
        raise

async def complete_todo(page_id: str) -> dict:
    """Mark a todo as complete in Notion"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{NOTION_BASE_URL}/pages/{page_id}",
                headers=headers,
                json={
                    "properties": {
                        "Status": {
                            "type": "status",
                            "status": {"name": "Done"}
                        }
                    }
                }
            )
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        logger.error("Request to Notion API timed out")
        raise
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in complete_todo: {str(e)}")
        raise

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
            logger.debug("Fetching todos from Notion...")
            todos = await fetch_todos()
            logger.debug(f"Raw API response: {safe_json_dumps(todos)}")
            
            formatted_todos = []
            today = datetime.now(timezone.utc).date()
            
            for todo in todos.get("results", []):
                try:
                    logger.debug(f"Processing todo: {safe_json_dumps(todo)}")
                    props = todo["properties"]
                    logger.debug(f"Todo properties: {safe_json_dumps(props)}")
                    
                    # Get due date
                    due_str = safe_get_property(props, "Due", "")
                    due_date = None
                    if due_str:
                        try:
                            due_date = datetime.fromisoformat(due_str.replace("Z", "+00:00")).date()
                        except ValueError as e:
                            logger.error(f"Error parsing due date {due_str}: {e}")
                    
                    # Get task name safely
                    task_name = safe_get_property(props, "Task name", "")
                    
                    # Get task ID safely
                    task_id = safe_get_property(props, "Task ID", "")
                    
                    formatted_todo = {
                        "id": todo["id"],
                        "task_id": task_id,
                        "task": task_name,
                        "status": safe_get_property(props, "Status", ""),
                        "assignee": safe_get_property(props, "Assignee", ""),
                        "due": due_str,
                        "priority": safe_get_property(props, "Priority", ""),
                        "tags": safe_get_property(props, "Tags", []),
                        "sprint": safe_get_property(props, "Sprint", ""),
                        "project": safe_get_property(props, "Project", ""),
                        "github_pr": safe_get_property(props, "GitHub PR", ""),
                        "created": todo["created_time"]
                    }
                    logger.debug(f"Formatted todo: {safe_json_dumps(formatted_todo)}")
                    
                    if name == "show_today_todos":
                        if not due_date:
                            logger.debug(f"Skipping todo without due date: {formatted_todo['task']}")
                            continue
                        if due_date != today:
                            logger.debug(f"Skipping non-today todo: {formatted_todo['task']} (due: {due_date}, today: {today})")
                            continue
                        
                    formatted_todos.append(formatted_todo)
                except Exception as e:
                    logger.error(f"Error processing todo: {e}")
                    continue
            
            logger.info(f"Successfully processed {len(formatted_todos)} todos")
            response = [
                TextContent(
                    type="text",
                    text=safe_json_dumps(formatted_todos)
                )
            ]
            logger.debug(f"Returning response: {safe_json_dumps(response)}")
            return response
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