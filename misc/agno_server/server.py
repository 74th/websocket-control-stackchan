from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.tools.workspace import Workspace
from fastapi.middleware.cors import CORSMiddleware

workbench = Agent(
    name="Workbench",
    model="openai:gpt-5.4-mini",
    # model="openai:google/gemma-4-e4b",
    instructions="あなたは親切な音声アシスタントです。音声で返答するため、マークダウンは記述せず、簡潔に答えてください。だいたい3文程度で答えてください。",
    tools=[Workspace(".",
        allowed=[],
        # confirm=["write", "edit", "delete", "shell"],
    )],  # read/write/edit/shell in this directory
    enable_agentic_memory=True,  # remembers across sessions
    add_history_to_context=True,  # include past runs
    num_history_runs=3,  # last 3 conversations
)

# Serve via AgentOS
agent_os = AgentOS(agents=[workbench], tracing=True, db=SqliteDb(db_file="agno.db"))
app = agent_os.get_app()

# uv run fastapi dev ./misc/agno_server/server.py --host 0.0.0.0
