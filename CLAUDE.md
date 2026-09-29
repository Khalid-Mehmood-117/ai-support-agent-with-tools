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
- Do not tune the prompt to make failing eval scenarios pass. Code guardrails are a different thing
  and are allowed: a guardrail is deterministic code that enforces a rule on every conversation
  (the refund policy check, the approval interrupt, the step limit, the action-claim guard), is
  covered by unit tests, and is visible in the trace when it acts. Prompt tuning is rewording
  instructions to change model behaviour on specific cases. A guardrail must never be written to
  match one scenario's wording.
- The action-claim guard (claim_guard.py) runs on every final reply: a reply may not claim a refund,
  ticket or email unless the matching tool succeeded in this conversation. When it fires it removes
  the false sentences, offers the action instead and logs a claim_guard step in the trace.
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
- Done: M2 evaluation (2026-09-29). eval/scenarios.json has 25 scripted conversations in 11
  categories, 8 of them adversarial (3 prompt injections, 2 ownership, 1 change of mind, 2 tool
  timeouts). eval/run_eval.py runs each in-process with real gpt-4o-mini on a fresh copy of the seed
  database, scripts staff approvals, scores task success (database end state plus a gpt-4o-mini
  judge), tool sequence (ordered subsequence plus forbidden tools) and policy violations (checked in
  code against seed ground truth), and reports tool calls, latency, tokens and estimated cost.
- M2 verification: four full runs. Final run (eval/results.md): task success 22/25 (88%), tool
  sequence 23/25 (92%), policy violations 0, 1.2 tool calls, 3.1 s and about $0.0005 per
  conversation. Run 1 had 1 violation, a false positive in the eval judge (a past refund counted as
  a new refund claim); fixed in run_eval.py. Known failures are documented in results.md: the fake
  SYSTEM message makes the model skip the eligibility check (code guardrail blocked the refund every
  time), the safety scenario sometimes announces a ticket without calling the tool, the agent lists
  the requester's own orders unasked, and the change of mind reply is not explicit.
  pytest: 52 passed (10 new tests prove every violation check fires on bad data).
- Design changes in M2: search_orders_by_email description rewritten, prompt rules added for acting
  in the same reply and for asking before escalating after a tool error, safety advice rule added.
- Eval history (2026-09-29): run_eval.py now appends every full run to eval/history.md (never
  rewritten; use --note to record what changed). Runs 1 to 4 backfilled from saved reports. Run 5,
  with no agent or prompt changes, scored 23/25 success, 23/25 tools, 0 violations (change_of_mind
  passed this time), so treat task success as roughly 88 to 92 percent. Owner instruction: do not
  tune the prompt to the remaining failing scenarios. pytest: 54 passed.
- Possible follow-ups: re-prompt in code when a reply promises an action without a tool call; run
  the eval several times and report per-scenario pass rates, since temperature 0 is not deterministic.
- Done: action-claim guard (2026-09-29). backend/app/claim_guard.py plus a claim_guard graph node
  after every final reply. Regex rules per action (refund, ticket, email) against tool steps with
  status ok anywhere in the conversation (an earlier turn counts, so "I've already escalated,
  TCK-0001" in turn 2 stays). False sentences and leftover promises ("Let me do that now") are
  removed, an honest offer is appended, and the step logs the claims plus original and corrected
  reply. 21 tests (7 real false replies from eval transcripts fire, 7 honest replies do not, graph
  cases). pytest: 75 passed.
- Eval run 6 with --note "action-claim guard added": 21/25 success, 23/25 tools, 0 violations,
  1 guard correction. safety_issue still fails, but honestly: the reply keeps the safety advice and
  offers to create the ticket instead of claiming "Creating a support ticket now". The guard cannot
  make the scenario pass because it corrects claims and does not perform actions.
  tool_timeout_then_escalate failed because the reply left out the ticket id (guard not involved;
  it passed in runs 4 and 5). The "Let me do that now" filler rule was added after run 6 and only
  changes the wording of corrections.
- Done: M3 streaming and UI (2026-09-29). Backend: POST /conversations/{id}/messages/stream and
  /approval/stream (SSE events step, turn, error); the JSON endpoints run the same turn runner.
  Frontend in frontend/ (Next.js 16.3.6, React 19.2.8, Tailwind 4, config copied from project 1,
  light theme): lib/api.ts (typed client, fetch based SSE reader), lib/useConversation.ts (state),
  ChatPanel with sample prompt chips, MessageBubble (guard corrected label), ApprovalCard (order,
  customer, items, reason, policy check, note, Approve and Reject), TracePanel and TraceStep (model,
  tool with status badge and collapsible result, staff approval, step limit, claim guard).
- M3 verification: production build (next build, tsc and eslint clean) on port 3001 against the
  local backend on 8000 with the real key, driven by Playwright in headless Chrome: order lookup
  ORD-1004 answered with tracking; refund ORD-1007 showed trace steps before the approval card
  (live stream), then Approve with a note wrote REF-0003 (checked in the database); ORD-1010 was
  denied by check_refund_eligibility with no approval card; the fake SYSTEM message made the model
  call create_refund, which the policy recheck denied, again with no approval card. Zero console
  and page errors. At 390 px width the first build overflowed by 432 px; fixed with min-w-0 grid
  columns and word breaking, then 0 px. Screenshots docs/screenshots/00-empty to 06-mobile.
  pytest: 80 passed (5 new streaming tests).
- Eval run 7 after the streaming refactor, no agent changes: 23/25 success, 23/25 tools,
  0 violations, 1 guard correction (safety_issue).
- Fix found during M3: `python -m app.seed --reset` used to delete store.db before failing on the
  checkpoint file held open by a running backend (Windows), leaving the backend without a store.
  It now deletes the checkpoint file first and exits with "Stop the backend" if it is in use, so a
  failed reset changes nothing.
- Screenshots are made with Playwright from project 1's venv (not a dependency of this repo).
- Next: M4 (Docker Compose, README with demo GIF, Mermaid diagram and eval results).
