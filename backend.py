import json
import re
from typing import Literal,TypedDict
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph,END,START
from pydantic import BaseModel,Field,ValidationError

load_dotenv()

# set up the llm
llm_model = init_chat_model(model="gemini-2.5-flash",model_provider="google_genai")

# graph state
class State(TypedDict):
    topic: str
    draft: str
    feedback: str
    decision: str
    revision_count: int

# pydantic schema for the review agent
class Review(BaseModel):
    decision: Literal["PASS","REVISE"] = Field(description="PASS only if the answer satisfies every review rule; otherwise REVISE")
    feedback: str = Field(description="Short, specific feedback. Empty string when decision is PASS.")
    
# Pydantic llm
llm_with_struct = llm_model.with_structured_output(Review)

# Utility Functions 

# This makes sure the llm response is in text format
def content_to_text(content) -> str:
    if isinstance(content,str):
        return content
    if isinstance(content,list):
        parts = []
        for item in content:
            if isinstance(item,dict):
                text = item.get("text") or item.get("content")
                if text: 
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(content)

# this function parses the content for review
def parse_review(raw_text: str) ->  Review:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*",text,flags=re.IGNORECASE)
    text = re.sub(r"\s*```$","",text)
    
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        
        match = re.search(r"\{.*\}",text,flags=re.DOTALL)
        
        if not match:
            raise ValueError(f"Reviewer returned invalid JSON: {raw_text}")
        payload = json.loads(match.group(0))
    
    try:
        review = Review.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Reviewer returned an invalid review object: {payload} from exc")
    
    if review.decision == "PASS":
        review.feedback = ""
    return review

# AGENT 1: WRITER AGENT
def writer_agent(state: State):
    response = llm_model.invoke(
        [
            {
                "role": "system",
                "content": (
                    "You are the WRITER agent in a self-correcting multi-agent system. "
                    "You are a beginner-friendly teacher. Explain the topic in 120-100 words."
                    "Use simple language, one everyday analogy, and one tiny example. "
                ),
            },
            {"role": "user","content": f"Explain: {state["topic"]}"},
        ]
    )
    return {
        "draft": content_to_text(response.content),
        "feedback": "",
        "decision": "",
        "revision_count": 0
    }

# REVIEWER / VERIFIER IN THE LOOP
# def reviewer_agent(state: State):
#     response = llm_with_struct.invoke(
#         [
#             {
#                 "role": "system",
#                 "content": (
#                     "You are the REVIEWER agent in a self-correcting multi-agent system. "
#                     "Check the answer using ONLY these rules:\n"
#                     "1. It is easy for a beginner.\n"
#                     "2. It contains an everyday analogy.\n"
#                     "3. It contains a tiny concrete example.\n"
#                     "4. It stays focused on the requested topic.\n"
#                     "If any rule fails, choose REVISE and give one or two precise improvements.\n\n"
#                     "Return ONLY valid JSON in exactly this shape:\n"
#                     '{"decision":"PASS|REVISE","feedback":"..."}\n'
#                     "When the decision is PASS, feedback must be an empty string."
#                 ),
#             },
#             {
#                 "role": "user",
#                 "content": f"Topic: {state['topic']}\n\nAnswer:\n{state['draft']}",
#             },
#         ]
#     )
#     review = parse_review(content_to_text(response.content))
#     return {"decision": review.decision, "feedback": review.feedback}

def reviewer_agent(state: State):
    review = llm_with_struct.invoke(
        [
            {
                "role": "system",
                "content": (
                    "You are the REVIEWER agent in a self-correcting multi-agent system. "
                    "Check the answer using ONLY these rules:\n"
                    "1. It is easy for a beginner.\n"
                    "2. It contains an everyday analogy.\n"
                    "3. It contains a tiny concrete example.\n"
                    "4. It stays focused on the requested topic.\n"
                    "If any rule fails, choose REVISE and give one or two precise improvements.\n"
                    "If all rules pass, choose PASS and set feedback to an empty string."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Topic: {state['topic']}\n\n"
                    f"Answer:\n{state['draft']}"
                ),
            },
        ]
    )

    return {
        "decision": review.decision,
        "feedback": review.feedback,
    }

# REVISER AGENT 
def reviser(state: State):
    response = llm_model.invoke(
        [
            {
                "role": "system",
                "sontent": (
                    "You are the REVISER agent in a self-correcting multi-agent system."
                    "Improve the answer using the reviewer feedback. Keep it beginner-friendly "
                    "and concise. Return only the improved answer."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Topic: {state['topic']}\n\n"
                    f"Current answer:\n{state["draft"]}\n\n"
                    f"Reviewer feedback: \n{state['feedback']}"
                ),
            },
        ]
    )
    return {
        'draft': content_to_text(response.content),
        "revision_count": state['revision_count']
    }

def route_after_review(state: State):
    if state['decision'] == 'PASS':
        return "done"
    if state['revision_count'] >= 5:
        return "done"
    return "revise"

# build the agent

graph = StateGraph(State)

graph.add_node("writer_node",writer_agent)
graph.add_node("reviewer_node",reviewer_agent)
graph.add_node("revise_node",reviewer_agent)

# add the edges
graph.add_edge(START,"writer_node")
graph.add_edge("writer_node","reviewer_node")
graph.add_conditional_edges("reviewer_node",route_after_review,{"revise":"revise_node","done":END})
graph.add_edge("revise_node","reviewer_node")

agent = graph.compile()


# utility display function
def get_runtime_info() -> dict:
    return {
        "provider": llm_model.name,
        "name": "Multi Self Correcting Agent",
        "max_revisions": 5
    }

# the function that runs the full pipeline
def run_workflow(topic:str):
    
    # define the input state/ how the agent will get input
    initial_state: State = {
        "topic": topic,
        "draft":"",
        "feedback":"",
        "decision": "",
        "revision_count": 0,
    }
    
    final_state = initial_state.copy()
    
    events = []
    
    # we will make use of streaming in the agent so that it can work in our user interface
    for update in agent.stream(initial_state,stream_node="updates"):
        for node_name,values in update.items():
            final_state.update(values)
            model_for_agent = {
                "writer": llm_model,
                "reviewer": llm_with_struct,
                "reviser": llm_model,
            }.get(node_name,llm_model.name)
            
            events.append(
                {
                    "agent": node_name,
                    "draft": values.get("draft",""),
                    "decision": values.get("decision",""),
                    "feedback": values.get("feedback",""),
                    "revision_count": final_state["revision_count"],
                    "provider": "Google Gemini API 😁😁"
                }
            )
    info = get_runtime_info()
    
    return {
        "topic": topic,
        "events": events,
        "final_answer": final_state['draft'],
        "revision_count": final_state['revision_count'],
        **info
    }

# we can test in terminal using this

def run_demo(topic: str):
    result = run_workflow(topic)
    print("\n*** SELF-CORRECTING MULTI-AGENT DEMO ***")
    print(f"Provider: {result['provider']}\n") 
    print(f"Full Response: {result}")
    print(f"Final Response: {result['final_decision']}")
    

# if __name__ == "__main__":
#     topic = input("Enter a topic (example: What is an AI Agent? ): ").strip()
#     if not topic:
#         topic = "What is an AI Agent?"
#     run_demo(topic)