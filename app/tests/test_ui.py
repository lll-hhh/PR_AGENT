import time
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QDesktopServices

from merge_monitor import ui


def test_wait_duration_text_formats_open_and_merged_prs():
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    assert ui.wait_duration_text("2026-10-28T10:00:00Z", now=now) == "2天 2小时"
    assert ui.wait_duration_text("2026-10-30T11:55:55Z", "2026-10-30T12:00:00Z") == "4分 5秒"
    assert ui.wait_duration_text(None, now=now) == "待更新"


def test_wait_duration_seconds_supports_sorting():
    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    assert ui.wait_duration_seconds({"created_at": "2026-10-29T10:00:00Z"}, now=now) == 93_600
    assert ui.wait_duration_seconds({"created_at": "bad"}, now=now) is None


@pytest.fixture(scope="session")
def application():
    app = ui.create_application()
    yield app
    app.closeAllWindows()
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.quit()


@pytest.fixture
def window(application, monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "cache_path", lambda: tmp_path / "snapshot.json")
    widget = ui.MainWindow(offline=True)
    widget.snapshot = {"account": "contributor", "items": [{
        "repository": "example-org/example-repo", "number": 1, "title": "Example contribution",
        "url": "https://github.com/example-org/example-repo/pull/1", "state": "open",
        "details_ok": True, "signals_ok": True,
    }]}
    widget.render()
    yield widget
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_pr_sections_show_each_pr_and_repository_view_deduplicates(window, application):
    item = {"repository": "org/repo", "number": 1, "title": "Fix", "url": "https://github.com/org/repo/pull/1",
            "state": "open", "details_ok": True, "signals_ok": True}
    window.snapshot = {"items": [item, dict(item, number=2, draft=True), dict(item, number=3, state="closed"),
                                  dict(item, number=4, state="closed", merged_at="2026-10-29T12:00:00Z")]}
    for phase, numbers in [("waiting", [1]), ("action", [2, 3]), ("merged", [4])]:
        window.tabs[phase].click()
        application.processEvents()
        assert [row.item["number"] for row in window.rows] == numbers
    window.tabs["repositories"].click()
    assert len(window.rows) == 1
    assert window.rows[0].repository == "org/repo"


def test_opening_a_new_window_fetches_fresh_status_each_time(application, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ui, "cache_path", lambda: tmp_path / "snapshot.json")
    monkeypatch.setattr(ui, "existing_credential", lambda: "memory-only-test-token")

    def sync(client, previous):
        calls.append(1)
        return {"account": "contributor", "items": [], "partial": False, "updated_at": "2026-10-29T12:00:00Z"}

    monkeypatch.setattr(ui.GitHubClient, "sync", sync)
    for _ in range(2):
        widget = ui.MainWindow()
        widget.show()
        deadline = time.monotonic() + 5
        while (not widget.live or widget.worker.isRunning()) and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.01)
        assert widget.live
        assert widget.timer.interval() == 60_000
        assert "已同步" in widget.footer.text()
        assert "token" not in (tmp_path / "snapshot.json").read_text(encoding="utf-8")
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(calls) == 2


def test_offline_failure_preserves_rows_and_marks_the_record_stale(window):
    count = len(window.rows)
    window.sync_failed("连接失败")
    assert len(window.rows) == count
    assert "上次记录" in window.footer.text()
    assert "连接失败" in window.footer.text()
    assert not window.live


def test_row_opens_only_its_github_pr(window, monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    window.rows[0].pr_links[0].open_link()
    assert opened == [window.rows[0].item["url"]]
    window.rows[0].pr_links[0].url = "https://example.com/"
    window.rows[0].pr_links[0].open_link()
    assert len(opened) == 1


def test_visible_contribution_totals_count_only_merged_prs(window):
    base = {"repository": "org/repo", "title": "Fix", "url": "https://github.com/org/repo/pull/1",
            "stats_ok": True, "details_ok": True, "signals_ok": True, "created_at": "2026-10-29T10:00:00Z"}
    window.snapshot = {"items": [dict(base, number=1, state="open", additions=999, deletions=999),
                                  dict(base, number=2, state="closed", merged=True, additions=12, deletions=3)],
                       "repositories": {"org/repo": {"stars": 12345, "metadata_ok": True}}}
    window.set_filter("repositories")
    card = window.rows[0]
    assert card.metrics["累计贡献行数"].text() == "+12 / −3"
    assert card.metrics["累计贡献次数"].text() == "1 次"
    assert set(window.tabs) == {"waiting", "action", "merged", "repositories", "candidates"}
    assert not card.pr_links


def test_repository_view_shows_account_contribution_totals(window):
    window.snapshot = {
        "items": [{"repository": "org/repo", "number": 1, "state": "closed", "merged": True}],
        "repositories": {"org/repo": {"stars": 12345, "metadata_ok": True}},
        "contribution_totals": {"repositories": 1, "issues": 4, "issues_ok": True,
                                 "commits": 6, "commits_ok": True, "merges": 1,
                                 "additions": 16, "deletions": 3, "lines_ok": True,
                                 "stars": 12345, "stars_ok": True, "downloads": 88,
                                 "downloads_ok": True},
    }
    window.set_filter("repositories")
    assert {key: value.text() for key, value in window.total_values.items()} == {
        "repositories": "1", "issues": "4", "commits": "6", "merges": "1",
        "lines": "+16 / −3",
        "stars": "12,345", "downloads": "88",
    }


def test_pr_metrics_show_own_diff_and_stable_ordinal_instead_of_repository_totals(window):
    base = {"repository": "org/repo", "title": "Fix", "url": "https://github.com/org/repo/pull/2",
            "stats_ok": True, "details_ok": True, "signals_ok": True}
    # Deliberately put the newer, smaller PR first. Earlier history must count
    # toward its ordinal while its diff must not inflate this PR's line counts.
    window.snapshot = {"items": [dict(base, number=2, state="open", additions=7, deletions=2),
                                  dict(base, number=1, state="closed", merged=True, merged_at="2026-10-29T12:00:00Z", additions=100, deletions=20)]}
    for phase, number, lines, ordinal in [("waiting", 2, "+7 / −2", "第 2 次"),
                                          ("merged", 1, "+100 / −20", "第 1 次")]:
        window.set_filter(phase)
        card = window.rows[0]
        assert card.item["number"] == number
        expected = {"本次贡献行数": lines, "贡献序号": ordinal}
        if phase == "waiting":
            expected["后提交先合并"] = "待更新"
            expected["已等待"] = "待更新"
        else:
            expected["总等待时长"] = "待更新"
        assert {name: value.text() for name, value in card.metrics.items()} == expected


def test_draft_has_diff_without_consuming_contribution_number(window):
    item = {"repository": "org/repo", "number": 1, "title": "Draft", "url": "https://github.com/org/repo/pull/1",
            "state": "open", "draft": True, "stats_ok": True, "additions": 9, "deletions": 1}
    window.snapshot = {"items": [item]}
    window.set_filter("action")
    assert window.rows[0].metrics["本次贡献行数"].text() == "+9 / −1"
    assert window.rows[0].metrics["贡献序号"].text() == "草稿 · 未计次"
    window.set_filter("repositories")
    assert not window.rows


def test_switching_sections_hides_previous_cards_before_deferred_deletion(window, application):
    window.show()
    application.processEvents()
    previous_card = window.rows[0]
    assert previous_card.isVisible()
    window.tabs["action"].click()
    assert previous_card.isHidden()


def test_no_merged_pr_means_no_contributed_repository_even_when_open_pr_exists(window):
    window.snapshot = {"items": [{"repository": "org/repo", "number": 1, "title": "Fix", "state": "open"}]}
    window.set_filter("repositories")
    assert not window.rows
    assert window.tabs["repositories"].text().endswith("0")


def test_repository_category_and_subcategory_filters_only_include_merged_repos(window):
    base = {"number": 1, "title": "Fix", "state": "closed", "merged": True, "stats_ok": True, "additions": 5, "deletions": 1}
    window.snapshot = {"items": [dict(base, repository="ANative-Lab/EvoAgentX"),
                                  dict(base, repository="microsoft/agent-lightning"),
                                  dict(base, repository="stanfordnlp/dspy"),
                                  dict(base, repository="open/agent", state="open", merged=False)]}
    window.set_filter("repositories")
    assert len(window.rows) == 3
    window.category_tree.setCurrentItem(window.category_items[("Agent", None)])
    assert {r.repository for r in window.rows} == {"ANative-Lab/EvoAgentX", "microsoft/agent-lightning"}
    window.category_tree.setCurrentItem(window.category_items[("Agent", "自进化与搜索优化")])
    assert [r.repository for r in window.rows] == ["ANative-Lab/EvoAgentX"]
    window.category_tree.setCurrentItem(window.category_items[("LLM", None)])
    assert [r.repository for r in window.rows] == ["stanfordnlp/dspy"]


def test_star_type_and_wait_sort_filters_apply_to_pr_rows(window):
    base = {"title": "Fix", "state": "open", "details_ok": True, "signals_ok": True,
            "created_at": "2026-10-29T10:00:00Z", "stats_ok": True, "additions": 1, "deletions": 1}
    window.snapshot = {"items": [dict(base, repository="org/agent", number=1, url="https://github.com/org/agent/pull/1"),
                                  dict(base, repository="org/llm", number=2, url="https://github.com/org/llm/pull/2",
                                       created_at="2026-10-29T11:00:00Z")],
                       "repositories": {"org/agent": {"stars": 8000, "metadata_ok": True, "description": "agent framework"},
                                        "org/llm": {"stars": 4000, "metadata_ok": True, "description": "LLM tools"}}}
    window.set_filter("waiting")
    window.star_filter.setCurrentIndex(2)
    assert [row.item["number"] for row in window.rows] == [1]
    window.star_filter.setCurrentIndex(0)
    window.sort_filter.setCurrentIndex(2)
    assert [row.item["number"] for row in window.rows] == [1, 2]
    window.type_filter.setCurrentIndex(2)
    assert [row.item["number"] for row in window.rows] == [2]


def test_ignored_cached_draft_is_hidden_from_counts_and_rows(window, monkeypatch):
    window.snapshot = {"items": [{"repository": "contributor/example-repo", "number": 1, "draft": True,
                                   "state": "open", "title": "Draft", "url": "https://github.com/contributor/example-repo/pull/1"}]}
    monkeypatch.setattr(ui, "load_rules", lambda: {
        "account": "contributor", "ignored_prs": ["contributor/example-repo#1"],
        "handled_actions": {}, "repository_categories": {},
    })
    window.set_filter("action")
    assert not window.rows and not window.items
    assert window.tabs["action"].text().endswith("0")


def test_later_merge_indicator_opens_evidence_and_does_not_change_action_status(window, monkeypatch):
    item = {"repository": "org/repo", "number": 42, "title": "Fix", "url": "https://github.com/org/repo/pull/42",
            "state": "open", "created_at": "2026-10-29T10:00:00Z", "details_ok": True, "signals_ok": True}
    merged = {"number": 45, "author": "other", "title": "Another fix", "url": "https://github.com/org/repo/pull/45",
              "created_at": "2026-10-29T11:00:00Z", "merged_at": "2026-10-29T12:00:00Z"}
    info = {"later_merges_ok": True, "later_merges_since": item["created_at"], "later_merges": [merged]}
    window.snapshot = {"items": [item], "repositories": {"org/repo": info}}
    window.set_filter("waiting")
    card = window.rows[0]
    assert card.metrics["后提交先合并"].text() == "1 个 · #45"
    assert card.metrics["最近先合并时间"].text() == ui.date_text(merged["merged_at"])
    assert "Another fix" in card.metrics["后提交先合并"].toolTip()
    assert window.tabs["action"].text().endswith("0")
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    card.metrics["后提交先合并"].open_link()
    assert opened == [merged["url"]]
    info["later_merges_ok"] = False
    window.render()
    assert "旧" in window.rows[0].metrics["后提交先合并"].text()
    assert "旧" in window.rows[0].metrics["最近先合并时间"].text()


def test_complete_empty_merge_check_is_distinct_from_unavailable_check(window):
    item = {"repository": "org/repo", "number": 42, "title": "Fix", "url": "https://github.com/org/repo/pull/42",
            "state": "open", "created_at": "2026-10-29T10:00:00Z", "details_ok": True, "signals_ok": True}
    info = {"later_merges_ok": True, "later_merges_since": item["created_at"], "later_merges": []}
    window.snapshot = {"items": [item], "repositories": {"org/repo": info}}
    window.set_filter("waiting")
    assert window.rows[0].metrics["后提交先合并"].text() == "暂未发现"
    info["later_merges_ok"] = False
    window.render()
    assert window.rows[0].metrics["后提交先合并"].text() == "待更新"
