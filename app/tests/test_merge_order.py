from datetime import datetime, timedelta, timezone

from merge_monitor.github import GitHubClient, SyncError
from merge_monitor.state import later_merge_summary


def pending(**updates):
    return {"repository": "org/repo", "number": 42, "state": "open", "details_ok": True,
            "created_at": "2026-10-29T10:00:00Z", **updates}


def merged(number=43, **updates):
    return {"number": number, "author": "other", "created_at": "2026-10-29T11:00:00Z",
            "merged_at": "2026-10-29T12:00:00Z", "url": f"https://github.com/org/repo/pull/{number}", **updates}


def info(rows, **updates):
    return {"later_merges_ok": True, "later_merges_since": "2026-10-29T10:00:00Z",
            "later_merges": rows, **updates}


def test_only_later_submissions_actually_merged_by_other_authors_count():
    rows = [merged(), merged(44, created_at="2026-10-29T09:00:00Z"),
            merged(45, merged_at=None), merged(46, author="CONTRIBUTOR"),
            merged(47, author="dependabot[bot]"), merged(48, merged_at="2026-10-29T09:00:00Z"),
            merged(49, created_at="2026-10-29T10:00:00Z"), merged()]
    result = later_merge_summary(pending(), info(rows))
    assert result["known"] and result["count"] == 2
    assert {row["number"] for row in result["matches"]} == {43, 47}


def test_comparisons_are_per_pr_and_use_real_timestamps_not_numbers_or_comments():
    rows = [merged(1, created_at="2026-10-29T19:00:00+08:00", merged_at="2026-10-29T20:00:00+08:00"),
            merged(2, created_at="2026-10-29T13:00:00Z", merged_at="2026-10-29T14:00:00Z")]
    assert later_merge_summary(pending(), info(rows))["count"] == 2
    newer = later_merge_summary(pending(number=99, created_at="2026-10-29T12:00:00Z"), info(rows))
    assert newer["count"] == 1 and newer["latest"]["number"] == 2


def test_failed_or_incomplete_coverage_is_unknown_and_preserves_positive_evidence():
    result = later_merge_summary(pending(), info([merged()], later_merges_ok=False))
    assert not result["known"] and result["count"] is None
    assert result["latest"]["number"] == 43
    assert not later_merge_summary(pending(), info([], later_merges_since="2026-10-29T11:00:00Z"))["known"]
    assert not later_merge_summary(pending(details_ok=False), info([]))["known"]
    assert not later_merge_summary(pending(created_at=None), info([]))["known"]
    assert not later_merge_summary(pending(), {})["known"]


def test_monitoring_stops_when_own_pr_is_merged_closed_or_draft():
    for item in [pending(merged=True), pending(state="closed"), pending(draft=True)]:
        result = later_merge_summary(item, info([merged()]))
        assert not result["active"] and not result["matches"]


def test_repository_scan_follows_creation_pages_and_sorts_by_actual_merge_time(monkeypatch):
    client = GitHubClient()
    base = datetime(2026, 10, 29, 10, 1, tzinfo=timezone.utc)
    page_one = [{"number": 200 - i, "created_at": (base + timedelta(seconds=100-i)).isoformat(),
                 "merged_at": None} for i in range(100)]
    page_one[0]["merged_at"] = "2026-10-29T11:00:00Z"
    page_one[-1]["merged_at"] = "2026-10-29T12:00:00Z"
    page_two = [dict(merged(100, created_at="2026-10-29T10:00:30Z", merged_at="2026-10-29T13:00:00Z")),
                dict(merged(99, created_at="2026-10-29T09:00:00Z", merged_at="2026-10-29T14:00:00Z"))]
    seen = []
    def get(path, **params):
        assert params["sort"] == "created" and params["direction"] == "desc" and params["state"] == "closed"
        seen.append(params["page"])
        return page_one if params["page"] == 1 else page_two
    monkeypatch.setattr(client, "get", get)
    result = client.later_merge_info("org/repo", [pending()])
    assert seen == [1, 2] and result["later_merges_ok"]
    assert [row["number"] for row in result["later_merges"]] == [100, 101, 200]


def test_failed_repository_scan_keeps_last_verified_data_as_old(monkeypatch):
    client = GitHubClient()
    old = info([merged()], later_merges_checked_at="2026-10-29T12:00:00Z")
    def fail(*args, **kwargs):
        raise SyncError("offline")
    monkeypatch.setattr(client, "get", fail)
    result = client.later_merge_info("org/repo", [pending()], old)
    assert not result["later_merges_ok"] and result["later_merges"] == old["later_merges"]
    assert result["later_merges_checked_at"] == old["later_merges_checked_at"]


def test_sync_fetches_merge_order_once_per_repository_for_all_own_pending_prs(monkeypatch):
    client = GitHubClient()
    monkeypatch.setattr(client, "search", lambda: [
        {"repository_url": "https://api.github.com/repos/org/repo", "number": number} for number in (42, 43)])
    monkeypatch.setattr(client, "enrich", lambda source, previous: pending(number=source["number"], signals_ok=True, stats_ok=True))
    monkeypatch.setattr(client, "repository_info", lambda *args: {"metadata_ok": True, "activity_ok": True})
    calls = []
    def get(path, **params):
        calls.append(path)
        return [dict(merged(45), user={"login": "other"})]
    monkeypatch.setattr(client, "get", get)
    snapshot = client.sync()
    assert calls == ["/repos/org/repo/pulls", "/search/issues"]
    assert snapshot["partial"]
    assert snapshot["contribution_totals"]["issues"] is None
    assert all(later_merge_summary(item, snapshot["repositories"]["org/repo"])["count"] == 1 for item in snapshot["items"])
