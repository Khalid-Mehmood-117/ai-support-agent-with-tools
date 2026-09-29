# CLAUDE.md

## Project
AI customer support agent for a fictional online store. It answers order questions, checks refund
eligibility, creates refunds only after human approval, escalates to a human and drafts emails, all
through real tool calls against a SQLite store database. Every tool call is traced and shown in the UI.
Public portfolio project on GitHub, shown to Upwork clients. Code quality, README and evaluation
results matter.

## Owner
Khalid Mehmood, AI Engineer. Working with Claude Code as the daily coding partner. Windows machine,
repo at C:\Data\Projects\ai-support-agent-with-tools. Commits are authored as
Khalid Mehmood <khalidmehmood117@gmail.com> (repo-local git config).

## Stack (fixed, do not change without asking)
- Backend: Python 3.13, FastAPI
- Agent: LangGraph with langchain-openai tool calling, SQLite checkpointer for agent state
- Model: gpt-4o-mini, temperature 0
- Store database: SQLite via the standard library sqlite3 (no ORM)
- Frontend: Next.js (App Router, TypeScript, Tailwind)
- Tests: pytest with a scripted fake chat model (no network)

## Rules
- Follow PLAN.md. Milestones M1 to M4 in order. Do not start the next milestone until the current one is verified with real output.
- Never commit .env or any API key. .env.example is the only env file in git.
- Refund eligibility is decided by code in policy.py, never by the model. Both refund tools call the same function.
- create_refund always goes through the human approval interrupt. No code path writes a refund without an approve decision.
- Max tool-call steps per turn is enforced in the graph. Tool errors are caught, returned to the model as a result and never retried forever.
- Every turn records a trace (tool calls, arguments, results, timings) and returns it with the response.
- No em dashes in any file, README or comment.
- Prefer small, readable functions over clever code. This repo is read by clients.
- Commit after every verified milestone with a clear message, then push to origin main.
- Progress visibility: for any task with more than 3 steps, first write a numbered todo list of the steps, then mark each one done as you finish it and post a one-line note ("Step 2 of 6 done: seed data created"). Never go silent for a long stretch; if a step is taking longer than expected, say what is slow and why.

## Self-maintenance (mandatory)
At the end of every milestone, before telling the owner it is done:
1. Update the Status section below: what is complete, what was verified and how, what is next.
2. Update PLAN.md if any design decision changed.
3. Commit CLAUDE.md and PLAN.md together with the milestone code.
Do this without being asked. A milestone is not complete until this is done.

## Status
- Environment verified (2026-09-29): Python 3.13.5, Docker 29.7.2 with Compose v5.4.0, Node 24.14.0,
  npm 11.9.0, Git 2.55.0. .env holds OPENAI_API_KEY plus FRONTEND_PORT=3001 and CORS_ORIGINS
  (port 3000 is taken on this machine). .env is gitignored.
- Done: PLAN.md, CLAUDE.md, .env.example, .gitignore. Plan approved 2026-09-29 with decisions:
  email ownership check on order and refund tools, fixed STORE_TODAY=2026-09-15, eval runs
  in-process on a fresh database copy, streaming deferred to M3 (M1 is JSON only).
- Done: M1 agent, tools and API (2026-09-29). backend/app: SQLite schema and seed (8 customers,
  12 products, 20 orders in every state), policy.py (pure eligibility function), tools.py (six tools
  with Pydantic argument models and an email ownership check), graph.py (LangGraph with agent,
  approval, tools and step_limit nodes), service.py (turns, approvals, trace storage), FastAPI routes
  POST /conversations, POST /conversations/{id}/messages, POST /conversations/{id}/approval,
  GET /conversations/{id}, GET /health. Pinned versions in backend/requirements.txt
  (langgraph 1.2.12, langchain-openai 1.6.6, fastapi 0.141.1).
- M1 verification: uvicorn run locally with the real key and gpt-4o-mini. Order lookup ORD-1004
  called get_order_status and answered with FastShip tracking and the 2026-09-17 expected date.
  Refund ORD-1007 called check_refund_eligibility then create_refund, returned awaiting_approval with
  the approval payload (Tom Becker, 119.00, reason, policy check), and after approve wrote REF-0003
  and set the order to refunded. Refund ORD-1010 (31 days) was denied by check_refund_eligibility
  with OUTSIDE_WINDOW and no approval was requested. A pending approval survived a server restart
  (SQLite checkpointer) and was then rejected, with no refund written. pytest: 42 passed in 4.6 s
  (fake model, no network).
- Design notes from M1: sync routes and sync graph (simpler than async here). Approval is its own
  node because LangGraph re-runs a node on resume. Trace duration_ms excludes approval wait time.
  Demo data is reset with `python -m app.seed --reset` from backend/.
- Next: M2 (25 eval scenarios, runner, results.md).
