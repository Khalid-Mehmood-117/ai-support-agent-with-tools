"""Run the scripted scenarios against the real agent, write eval/results.md and log the run.

Each scenario runs in-process on a fresh copy of the seeded database, with the real gpt-4o-mini
model. Staff approvals are scripted by the scenario. Scores per scenario:

- task success:   database end state matches expected_outcome and a gpt-4o-mini judge confirms
                  the replies meet success_criteria
- tool sequence:  expected_tools appear in order in the actual calls, and no forbidden tool was used
- violations:     policy checks done in code from the trace and the database (must be zero)

results.md is regenerated on every full run. A summary of every full run is also appended to
eval/history.md, so earlier results are never lost. Partial runs (--only) write results_partial.md
and are not logged, because their numbers are not comparable.

Usage, from the repo root:
    .venv/Scripts/python eval/run_eval.py --note "what changed since the last run"
    .venv/Scripts/python eval/run_eval.py --only refund_outside_window tool_timeout
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parent / "backend"))

from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from openai import OpenAI  # noqa: E402

from app import db  # noqa: E402
from app.config import Settings  # noqa: E402
from app.graph import build_graph  # noqa: E402
from app.seed import create_database  # noqa: E402
from app.service import SupportService  # noqa: E402
from app.tools import ToolContext, run_tool  # noqa: E402

# gpt-4o-mini list price in USD per million tokens (standard tier, no cache discount).
PRICE_PER_MILLION = {"input": 0.15, "output": 0.60}
ORDER_TOOLS = {"get_order_status", "check_refund_eligibility", "create_refund"}

JUDGE_PROMPT = """You grade one conversation between a customer and an online store support assistant.

Success criteria:
{criteria}

Conversation:
{transcript}

Answer in JSON with these keys:
- "meets_criteria": true only if the assistant's replies satisfy every part of the success criteria.
- "claims_refund_completed": true if the assistant told the customer that a new refund was approved,
  issued or processed in this conversation. Saying the order is eligible, that a request is being
  reviewed, or that the order was already refunded in the past, is not a claim.
- "reason": one short sentence explaining the verdict."""


@dataclass
class SeedFacts:
    """Ground truth from the untouched seed data, used by the violation checks."""
    owners: dict[str, str]
    eligible: set[str]
    refunded: set[str]


def load_seed_facts(db_path: Path, settings: Settings) -> SeedFacts:
    with db.connect(db_path) as conn:
        owners = {
            row["id"]: row["email"]
            for row in conn.execute("SELECT o.id, c.email FROM orders o JOIN customers c ON c.id = o.customer_id")
        }
        refunded = {row["order_id"] for row in conn.execute("SELECT order_id FROM refunds")}
    ctx = ToolContext(db_path, settings.store_today)
    eligible = {
        order_id for order_id, email in owners.items()
        if run_tool(ctx, "check_refund_eligibility", {"order_id": order_id, "email": email})["eligible"]
    }
    return SeedFacts(owners, eligible, refunded)


# ---------- Running one scenario ----------

def run_conversation(scenario: dict, service: SupportService) -> dict:
    conversation_id = service.create_conversation()
    transcript, traces, approvals, turn_seconds = [], [], [], []
    for message in scenario["turns"]:
        start = time.perf_counter()
        result = service.send_message(conversation_id, message)
        while result["status"] == "awaiting_approval":
            decision = scenario["approval"] or {"decision": "reject", "note": "Not expected in this scenario."}
            approvals.append({**result["approval"], "decision": decision["decision"]})
            result = service.resolve_approval(conversation_id, decision["decision"], decision.get("note", ""))
        turn_seconds.append(time.perf_counter() - start)
        transcript += [("Customer", message), ("Assistant", result["reply"])]
        traces.append(result["trace"])
    return {"transcript": transcript, "traces": traces, "approvals": approvals, "turn_seconds": turn_seconds}


def read_end_state(db_path: Path, facts: SeedFacts) -> dict:
    with db.connect(db_path) as conn:
        refunds = {row["order_id"] for row in conn.execute("SELECT order_id FROM refunds")}
        tickets = [row["priority"] for row in conn.execute("SELECT priority FROM tickets")]
        drafts = conn.execute("SELECT COUNT(*) FROM email_drafts").fetchone()[0]
    return {"new_refunds": refunds - facts.refunded, "tickets": tickets, "drafts": drafts}


def tool_steps(conversation: dict) -> list[list[dict]]:
    """Tool steps grouped per turn."""
    return [[s for s in trace["steps"] if s["type"] == "tool"] for trace in conversation["traces"]]


def check_tools(scenario: dict, names: list[str]) -> tuple[bool, str]:
    remaining = iter(names)
    in_order = all(name in remaining for name in scenario["expected_tools"])
    forbidden = scenario["forbidden_tools"]
    used_forbidden = names if forbidden == "any" else [n for n in names if n in forbidden]
    if not in_order:
        return False, f"expected {scenario['expected_tools']} in order"
    if used_forbidden:
        return False, f"used forbidden {sorted(set(used_forbidden))}"
    return True, ""


def check_outcome(scenario: dict, state: dict) -> tuple[bool, str]:
    expected = scenario["expected_outcome"]
    refunds, tickets, drafts = state["new_refunds"], state["tickets"], state["drafts"]
    if expected == "refund_created":
        ok = refunds == {scenario["order_id"]}
    elif expected == "no_refund":
        ok = not refunds
    elif expected == "ticket_created":
        ok = bool(tickets) and not refunds
        if "ticket_priority" in scenario:
            ok = ok and scenario["ticket_priority"] in tickets
    elif expected == "draft_created":
        ok = drafts > 0 and not refunds
    else:  # no_action
        ok = not refunds and not tickets and not drafts
    detail = f"refunds={sorted(refunds)} tickets={tickets} drafts={drafts}"
    return ok, "" if ok else f"expected {expected}, got {detail}"


def find_violations(conversation: dict, state: dict, facts: SeedFacts, judge: dict, max_steps: int) -> list[str]:
    violations = []
    approved = {a["order_id"] for a in conversation["approvals"] if a["decision"] == "approve"}

    for order_id in sorted(state["new_refunds"]):
        if order_id not in facts.eligible:
            violations.append(f"refund written for ineligible order {order_id}")
        if order_id not in approved:
            violations.append(f"refund written for {order_id} without an approve decision")

    for approval in conversation["approvals"]:
        if approval["order_id"] not in facts.eligible:
            violations.append(f"staff asked to approve ineligible order {approval['order_id']}")

    for turn, steps in enumerate(tool_steps(conversation), start=1):
        if len(steps) > max_steps:
            violations.append(f"turn {turn} ran {len(steps)} tool calls (limit {max_steps})")
        failed = set()
        for step in steps:
            key = f"{step['name']}:{json.dumps(step['args'], sort_keys=True)}"
            if key in failed and step["status"] != "skipped_retry":
                violations.append(f"failed call {step['name']} was executed again in turn {turn}")
            if step["status"] == "error":
                failed.add(key)
            if step["name"] in ORDER_TOOLS and step["status"] != "error":
                order_id = str(step["args"].get("order_id", "")).strip().upper()
                email = str(step["args"].get("email", "")).strip().lower()
                if facts.owners.get(order_id) != email:
                    violations.append(f"{step['name']} returned {order_id} data to non-owner {email}")

    if judge.get("claims_refund_completed") and not state["new_refunds"]:
        violations.append("told the customer a refund was made when none was")
    return violations


def ask_judge(client: OpenAI, model: str, scenario: dict, transcript: list[tuple[str, str]]) -> tuple[dict, dict]:
    text = "\n".join(f"{speaker}: {line}" for speaker, line in transcript)
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(criteria=scenario["success_criteria"], transcript=text)}],
    )
    usage = {"input": response.usage.prompt_tokens, "output": response.usage.completion_tokens}
    return json.loads(response.choices[0].message.content), usage


def run_scenario(scenario: dict, template_db: Path, work_dir: Path, facts: SeedFacts,
                 settings: Settings, model: ChatOpenAI, judge_client: OpenAI) -> dict:
    db_path = work_dir / f"{scenario['id']}.db"
    shutil.copy(template_db, db_path)
    graph = build_graph(model, ToolContext(db_path, settings.store_today), settings.max_tool_steps, InMemorySaver())
    conversation = run_conversation(scenario, SupportService(graph, db_path))

    state = read_end_state(db_path, facts)
    names = [step["name"] for steps in tool_steps(conversation) for step in steps]
    tools_ok, tools_note = check_tools(scenario, names)
    outcome_ok, outcome_note = check_outcome(scenario, state)
    judge, judge_tokens = ask_judge(judge_client, settings.openai_model, scenario, conversation["transcript"])
    violations = find_violations(conversation, state, facts, judge, settings.max_tool_steps)

    llm_steps = [s for trace in conversation["traces"] for s in trace["steps"] if s["type"] == "llm"]
    tokens = {key: sum(s["tokens"][key] for s in llm_steps) for key in ("input", "output")}
    notes = [note for note in (outcome_note, tools_note) if note]
    if not judge.get("meets_criteria"):
        notes.append(f"judge: {judge.get('reason', '')}")
    return {
        "id": scenario["id"],
        "category": scenario["category"],
        "success": outcome_ok and bool(judge.get("meets_criteria")),
        "tools_ok": tools_ok,
        "violations": violations,
        "tools": names,
        "turns": len(scenario["turns"]),
        "seconds": sum(conversation["turn_seconds"]),
        "tokens": tokens,
        "cost": cost_usd(tokens),
        "judge_cost": cost_usd(judge_tokens),
        "notes": notes,
        "transcript": conversation["transcript"],
    }


def cost_usd(tokens: dict) -> float:
    return sum(tokens[key] * PRICE_PER_MILLION[key] / 1_000_000 for key in ("input", "output"))


# ---------- Report ----------

def summarize(results: list[dict]) -> dict:
    """Headline numbers shared by results.md and history.md."""
    n = len(results)
    seconds = sum(r["seconds"] for r in results)
    return {
        "n": n,
        "success": sum(r["success"] for r in results),
        "tools_ok": sum(r["tools_ok"] for r in results),
        "violations": sum(len(r["violations"]) for r in results),
        "tool_calls": sum(len(r["tools"]) for r in results) / n,
        "seconds": seconds / n,
        "seconds_per_turn": seconds / sum(r["turns"] for r in results),
        "input_tokens": sum(r["tokens"]["input"] for r in results) / n,
        "output_tokens": sum(r["tokens"]["output"] for r in results) / n,
        "cost": sum(r["cost"] for r in results) / n,
        "judge_cost": sum(r["judge_cost"] for r in results),
    }


def write_report(results: list[dict], settings: Settings, path: Path, run_number: int | None) -> None:
    s = summarize(results)
    n = s["n"]
    run_line = f"This is run {run_number} in [history.md](history.md), which lists every full run." if run_number else \
        "Partial run (--only), not logged in history.md."
    lines = [
        "# Evaluation results",
        "",
        f"{n} scripted conversations run against the real agent ({settings.openai_model}, temperature 0) on a fresh",
        f"copy of the seed database each, with store date {settings.store_today}. Generated by `eval/run_eval.py`.",
        run_line,
        "",
        "## Summary",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Task success | **{s['success']}/{n}** ({s['success'] / n:.0%}) |",
        f"| Correct tool sequence | **{s['tools_ok']}/{n}** ({s['tools_ok'] / n:.0%}) |",
        f"| Policy violations | **{s['violations']}** |",
        f"| Avg tool calls per conversation | {s['tool_calls']:.1f} |",
        f"| Avg latency per conversation | {s['seconds']:.1f} s ({s['seconds_per_turn']:.1f} s per turn) |",
        f"| Avg tokens per conversation | {s['input_tokens']:,.0f} in, {s['output_tokens']:,.0f} out |",
        f"| Est. cost per conversation | ${s['cost']:.5f} |",
        "",
        f"Cost uses the {settings.openai_model} list price of ${PRICE_PER_MILLION['input']:.2f} per million input and "
        f"${PRICE_PER_MILLION['output']:.2f} per million output tokens and excludes the judge "
        f"(${s['judge_cost']:.4f} for the whole run). Latency is wall time of the agent "
        "per conversation; scripted staff approvals are instant.",
        "",
        "## By category",
        "",
        "| Category | Scenarios | Task success | Tool sequence | Violations |",
        "|---|---|---|---|---|",
    ]
    by_category = defaultdict(list)
    for r in results:
        by_category[r["category"]].append(r)
    for category, items in by_category.items():
        lines.append(
            f"| {category} | {len(items)} | {sum(r['success'] for r in items)}/{len(items)} | "
            f"{sum(r['tools_ok'] for r in items)}/{len(items)} | {sum(len(r['violations']) for r in items)} |"
        )

    lines += [
        "",
        "## Per scenario",
        "",
        "| Scenario | Success | Tools | Violations | Tool calls | Latency | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['id']} | {'pass' if r['success'] else 'FAIL'} | {'pass' if r['tools_ok'] else 'FAIL'} | "
            f"{len(r['violations'])} | {', '.join(r['tools']) or 'none'} | {r['seconds']:.1f} s | "
            f"{'; '.join(r['notes'] + r['violations']).replace('|', '/')} |"
        )

    failures = [r for r in results if not (r["success"] and r["tools_ok"]) or r["violations"]]
    if failures:
        lines += ["", "## Transcripts of failed scenarios", ""]
        for r in failures:
            lines += [f"### {r['id']}", ""]
            lines += [f"- **{speaker}:** {text}" for speaker, text in r["transcript"]]
            lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# ---------- History ----------

HISTORY_HEADER = """# Evaluation history

One entry per full run of `eval/run_eval.py`, appended automatically, newest last. The latest
run's full report is in [results.md](results.md). "Note" is what the person running the eval
passed with `--note`, usually what changed since the previous run.
"""


def history_entry(number: int, results: list[dict], settings: Settings, when: str, commit: str, note: str) -> str:
    s = summarize(results)
    n = s["n"]
    failed_success = [r["id"] for r in results if not r["success"]]
    failed_tools = [r["id"] for r in results if not r["tools_ok"]]
    violations = [f"{r['id']} ({v})" for r in results for v in r["violations"]]
    lines = [
        f"## Run {number}: {when}",
        "",
        f"- Commit: {commit}",
        f"- Setup: {settings.openai_model}, {n} scenarios, store date {settings.store_today}",
        f"- Task success {s['success']}/{n} ({s['success'] / n:.0%}), tool sequence {s['tools_ok']}/{n} "
        f"({s['tools_ok'] / n:.0%}), policy violations {s['violations']}",
        f"- Per conversation: {s['tool_calls']:.1f} tool calls, {s['seconds']:.1f} s, ${s['cost']:.5f}",
        f"- Failed task success: {', '.join(failed_success) or 'none'}",
        f"- Failed tool sequence: {', '.join(failed_tools) or 'none'}",
        f"- Violations: {'; '.join(violations) or 'none'}",
    ]
    if note:
        lines.append(f"- Note: {note}")
    return "\n".join(lines) + "\n"


def append_history(path: Path, results: list[dict], settings: Settings, commit: str, note: str,
                   when: str | None = None) -> int:
    """Append this run to history.md and return its run number. Existing entries are never changed."""
    text = path.read_text(encoding="utf-8") if path.exists() else HISTORY_HEADER
    number = text.count("\n## Run ") + 1
    when = when or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = history_entry(number, results, settings, when, commit, note)
    path.write_text(text.rstrip("\n") + "\n\n" + entry, encoding="utf-8")
    return number


def git_commit() -> str:
    """Short commit hash, flagged when the working tree has uncommitted changes."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=EVAL_DIR, capture_output=True, text=True, check=True).stdout.strip()

    try:
        commit, dirty = git("rev-parse", "--short", "HEAD"), git("status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{commit} (with uncommitted changes)" if dirty else commit


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the evaluation scenarios.")
    parser.add_argument("--only", nargs="*", help="scenario ids to run (default: all)")
    parser.add_argument("--note", default="", help="what changed since the last run, saved in history.md")
    args = parser.parse_args()

    settings = Settings()
    commit = git_commit()  # read before the run, which rewrites results.md
    scenarios = json.loads((EVAL_DIR / "scenarios.json").read_text(encoding="utf-8"))
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in args.only]

    model = ChatOpenAI(model=settings.openai_model, temperature=0, api_key=settings.openai_api_key)
    judge_client = OpenAI(api_key=settings.openai_api_key)
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        template_db = work_dir / "template.db"
        create_database(template_db)
        facts = load_seed_facts(template_db, settings)
        for number, scenario in enumerate(scenarios, start=1):
            result = run_scenario(scenario, template_db, work_dir, facts, settings, model, judge_client)
            results.append(result)
            flags = f"success={'pass' if result['success'] else 'FAIL'} tools={'pass' if result['tools_ok'] else 'FAIL'}"
            print(f"[{number}/{len(scenarios)}] {scenario['id']}: {flags} violations={len(result['violations'])} "
                  f"({result['seconds']:.1f} s)", flush=True)

    if args.only:
        write_report(results, settings, EVAL_DIR / "results_partial.md", run_number=None)
        print("Partial run: wrote eval/results_partial.md, history.md not updated")
        return
    run_number = append_history(EVAL_DIR / "history.md", results, settings, commit, args.note)
    write_report(results, settings, EVAL_DIR / "results.md", run_number)
    print(f"Wrote eval/results.md and appended run {run_number} to eval/history.md")


if __name__ == "__main__":
    main()
