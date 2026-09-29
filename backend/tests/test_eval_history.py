"""history.md is append-only: every full run adds an entry and earlier entries are never changed."""

from app.config import Settings
from tests.test_eval_checks import run_eval

SETTINGS = Settings(_env_file=None)


def result(scenario_id: str, success=True, tools_ok=True, violations=()):
    return {
        "id": scenario_id, "success": success, "tools_ok": tools_ok, "violations": list(violations),
        "tools": ["get_order_status"], "turns": 1, "seconds": 2.0,
        "tokens": {"input": 1000, "output": 100}, "cost": 0.0002, "judge_cost": 0.0001,
    }


def test_first_run_creates_the_file_with_a_header(tmp_path):
    path = tmp_path / "history.md"
    number = run_eval.append_history(path, [result("a"), result("b", success=False)], SETTINGS,
                                     "abc1234", "first run", when="2026-09-29 10:00 UTC")
    text = path.read_text(encoding="utf-8")
    assert number == 1
    assert text.startswith("# Evaluation history")
    assert "## Run 1: 2026-09-29 10:00 UTC" in text
    assert "- Commit: abc1234" in text
    assert "Task success 1/2 (50%)" in text
    assert "- Failed task success: b" in text
    assert "- Note: first run" in text


def test_later_runs_append_and_keep_earlier_entries(tmp_path):
    path = tmp_path / "history.md"
    run_eval.append_history(path, [result("a")], SETTINGS, "abc1234", "", when="t1")
    before = path.read_text(encoding="utf-8")

    number = run_eval.append_history(path, [result("a", violations=["bad thing"])], SETTINGS, "def5678", "", when="t2")
    after = path.read_text(encoding="utf-8")
    assert number == 2
    assert after.startswith(before.rstrip("\n"))
    assert "## Run 2: t2" in after
    assert "- Violations: a (bad thing)" in after
    assert "- Note:" not in after  # no note given
