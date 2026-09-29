"""The LangGraph agent.

    agent --(no tool calls)--> end
    agent --(too many tool calls this turn)--> step_limit --> end
    agent --(create_refund requested)--> approval --> tools --> agent
    agent --(other tool calls)--> tools --> agent

The approval node pauses the graph with interrupt() until a staff member approves or rejects.
It is a separate node because LangGraph re-runs a node from the start when it resumes, and the
tools node has side effects (tickets, drafts) that must not run twice.

Every node appends trace steps tagged with the current turn number.
"""

import json
import operator
import time
from typing import Annotated

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Checkpointer, interrupt

from app.prompts import system_prompt
from app.tools import ToolContext, ToolError, approval_request, openai_tool_schemas, run_tool

STEP_LIMIT_REPLY = (
    "I'm sorry, I couldn't finish this request automatically. "
    "I can pass it to a human support specialist if you'd like."
)


def merge_dicts(current: dict, new: dict) -> dict:
    return {**current, **new}


class AgentState(MessagesState):
    turn: int
    steps: Annotated[list[dict], operator.add]
    # Staff decisions keyed by the create_refund tool call id.
    approvals: Annotated[dict, merge_dicts]


def build_graph(
    model: BaseChatModel,
    ctx: ToolContext,
    max_tool_steps: int,
    checkpointer: Checkpointer = None,
):
    model_with_tools = model.bind_tools(openai_tool_schemas())
    system = SystemMessage(system_prompt(ctx.today))

    def agent(state: AgentState) -> dict:
        start = time.perf_counter()
        reply = model_with_tools.invoke([system, *state["messages"]])
        step = {
            "type": "llm",
            "turn": state["turn"],
            "duration_ms": _elapsed_ms(start),
            "tokens": _token_usage(reply),
            "tool_calls": [call["name"] for call in reply.tool_calls],
        }
        return {"messages": [reply], "steps": [step]}

    def route_after_agent(state: AgentState) -> str:
        calls = state["messages"][-1].tool_calls
        if not calls:
            return END
        if _tool_steps_this_turn(state) + len(calls) > max_tool_steps:
            return "step_limit"
        if any(call["name"] == "create_refund" for call in calls):
            return "approval"
        return "tools"

    def approval(state: AgentState) -> dict:
        decisions, steps = {}, []
        for call in state["messages"][-1].tool_calls:
            if call["name"] != "create_refund":
                continue
            request = approval_request(ctx, call["args"])
            if request is None:
                continue  # ineligible or invalid: create_refund will deny it without asking staff
            answer = interrupt({"tool_call_id": call["id"], **request})
            decision = _clean_decision(answer)
            decisions[call["id"]] = decision
            steps.append({
                "type": "approval",
                "turn": state["turn"],
                "order_id": request["order_id"],
                "amount": request["amount"],
                **decision,
            })
        return {"approvals": decisions, "steps": steps}

    def tools(state: AgentState) -> dict:
        messages, steps = [], []
        failed = _failed_call_keys(state)
        for call in state["messages"][-1].tool_calls:
            key = _call_key(call)
            start = time.perf_counter()
            if key in failed:
                result, status = _error("ALREADY_FAILED", "This exact call already failed in this turn. "
                                        "Do not retry it; explain the problem or offer escalation."), "skipped_retry"
            else:
                result, status = _execute(ctx, call, state["approvals"].get(call["id"]))
                if status == "error":
                    failed.add(key)
            messages.append(ToolMessage(json.dumps(result), tool_call_id=call["id"], name=call["name"]))
            steps.append({
                "type": "tool",
                "turn": state["turn"],
                "name": call["name"],
                "args": call["args"],
                "result": result,
                "status": status,
                "duration_ms": _elapsed_ms(start),
            })
        return {"messages": messages, "steps": steps}

    def step_limit(state: AgentState) -> dict:
        calls = state["messages"][-1].tool_calls
        skipped = _error("STEP_LIMIT", "Not run: the tool call limit for this turn was reached.")
        messages = [ToolMessage(json.dumps(skipped), tool_call_id=c["id"], name=c["name"]) for c in calls]
        messages.append(AIMessage(STEP_LIMIT_REPLY))
        step = {
            "type": "step_limit",
            "turn": state["turn"],
            "max_tool_steps": max_tool_steps,
            "skipped_calls": [call["name"] for call in calls],
        }
        return {"messages": messages, "steps": [step]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("approval", approval)
    graph.add_node("tools", tools)
    graph.add_node("step_limit", step_limit)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, ["approval", "tools", "step_limit", END])
    graph.add_edge("approval", "tools")
    graph.add_edge("tools", "agent")
    graph.add_edge("step_limit", END)
    return graph.compile(checkpointer=checkpointer)


def _execute(ctx: ToolContext, call: dict, approval: dict | None) -> tuple[dict, str]:
    """Run a tool and never raise: every failure becomes an error result for the model."""
    try:
        result = run_tool(ctx, call["name"], call["args"], approval)
    except ToolError as error:
        return _error(error.code, error.message), "error"
    except Exception as error:  # noqa: BLE001 - any tool crash must reach the model as a result
        return _error("TOOL_FAILED", str(error) or type(error).__name__), "error"
    return result, _result_status(result)


def _result_status(result: dict) -> str:
    if result.get("refunded") is False:
        return "rejected" if result["reason_code"] == "REJECTED_BY_STAFF" else "denied"
    return "ok"


def _error(code: str, message: str) -> dict:
    return {"error": code, "message": message, "retryable": False}


def _clean_decision(answer) -> dict:
    """Anything other than an explicit approve counts as a rejection."""
    answer = answer if isinstance(answer, dict) else {}
    decision = "approve" if answer.get("decision") == "approve" else "reject"
    return {"decision": decision, "note": str(answer.get("note") or "")}


def _call_key(call: dict) -> str:
    return f"{call['name']}:{json.dumps(call['args'], sort_keys=True)}"


def _failed_call_keys(state: AgentState) -> set[str]:
    return {
        _call_key(step)
        for step in state["steps"]
        if step["turn"] == state["turn"] and step["type"] == "tool" and step["status"] == "error"
    }


def _tool_steps_this_turn(state: AgentState) -> int:
    return sum(1 for step in state["steps"] if step["turn"] == state["turn"] and step["type"] == "tool")


def _token_usage(reply: AIMessage) -> dict:
    usage = reply.usage_metadata or {}
    return {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)}


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)
