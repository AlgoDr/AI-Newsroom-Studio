# crewagent.py
import json
import asyncio  # <-- Required to bridge Jupyter's event loop
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from crewai import Agent, Task, Crew, Process

class ScoredArticle(BaseModel):
    title: str = Field(..., description="The title of the news story")
    url: str = Field(..., description="The original URL of the news story")
    editorial_score: int = Field(..., description="Score from 1 to 100 based on impact, prominence, conflict, novelty")

class EditorialOutput(BaseModel):
    scored_news: List[ScoredArticle]

def managing_editor_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph Node that wraps your CrewAI Managing Editor Agent.
    Handles Jupyter Notebook async conflicts natively using kickoff_async().
    """
    print("\n🎬 [LangGraph Node via CrewAI]: Handing over data to Managing Editor...")
    
    titles = state.get("article_titles", [])
    links = state.get("article_links", [])
    
    zipped_results = [{"title": t, "link": l} for t, l in zip(titles, links)]
    search_data_to_evaluate = json.dumps(zipped_results)
    
    editor_agent = Agent(
        role='Managing Editor',
        goal='Evaluate and prioritize news stories based on high journalistic value.',
        backstory='You are a veteran Managing Editor for a major global news outlet. You ignore clickbait and prioritize high-impact stories.',
        verbose=False,
        memory=False
    )
    
    evaluation_task = Task(
        description=(
            f"Review the following raw search data:\n{search_data_to_evaluate}\n\n"
            "Evaluate each story out of 25 points across 4 parameters:\n"
            "1. IMPACT: Footprint on daily lives/money.\n"
            "2. PROMINENCE: Involvement of major players/governments.\n"
            "3. CONFLICT: Legal/ideological battles.\n"
            "4. NOVELTY: Unexpected breakthroughs.\n"
            "Combine these into a final editorial score out of 100."
        ),
        expected_output="A structured list of articles with their calculated editorial importance scores.",
        agent=editor_agent,
        output_json=EditorialOutput
    )
    
    crew = Crew(
        agents=[editor_agent],
        tasks=[evaluation_task],
        process=Process.sequential
    )
    
    # --- ASYNC EVENT LOOP RESOLUTION ---
    try:
        # Get the running Jupyter loop
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # If running outside a notebook environment (pure script)
        loop = None

    if loop and loop.is_running():
        # Force the async kickoff call to complete inside Jupyter's running thread loop
        print("⚡ [Environment]: Active Jupyter event loop found. Executing task asynchronously...")
        crew_result = loop.run_until_complete(crew.kickoff_async())
    else:
        # Standard fallback for basic scripts
        crew_result = crew.kickoff()
    
    # Extract structural components safely
    if hasattr(crew_result, 'json_dict') and crew_result.json_dict:
        final_json = crew_result.json_dict
    else:
        final_json = json.loads(crew_result.raw)
        
    return {"editorially_scored_news": final_json.get("scored_news", [])}