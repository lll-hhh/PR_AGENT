from copy import deepcopy

import pytest

from merge_monitor.github import GitHubClient, SyncError
from merge_monitor.state import lifecycle, status_label


def source(state="open"):
    return {"repository_url": "https://api.github.com/repos/org/repo", "number": 42,
            "html_url": "https://github.com/org/repo/pull/42", "title": "A fix",
            "state": state, "updated_at": "2026-10-29T12:00:00Z", "pull_request": {"merged_at": None}}


def test_search_paginates_instead_of_dropping_older_open_prs(monkeypatch):
    client = GitHubClient()
    pages = []

    def get(path, **params):
        pages.append(params["page"])
        items = [dict(source(), number=i) for i in range(100 if params["page"] == 1 else 1)]
        return {"total_count": 101, "items": items}

    monkeypatch.setattr(client, "get", get)
    assert len(client.search()) == 101
    assert pages == [1, 2]


def test_search_failure_does_not_look_like_empty_list(monkeypatch):
    client = GitHubClient()
    monkeypatch.setattr(client, "get", lambda *a, **k: {"incomplete_results": True, "total_count": 0, "items": []})
    with pytest.raises(SyncError):
        client.search()


def test_fresh_pr_details_override_search_index_lag_and_show_merge(monkeypatch):
    client = GitHubClient()
    pr = {"state": "closed", "merged": True, "merged_at": "2026-10-29T13:00:00Z",
          "title": "A fix", "updated_at": "2026-10-29T13:00:00Z"}
    monkeypatch.setattr(client, "get", lambda *a, **k: deepcopy(pr))
    result = client.enrich(source(), None)
    assert lifecycle(result) == "merged"
    assert status_label(result) == "已合并"


def test_unavailable_details_are_not_shown_as_current_review_state(monkeypatch):
    client = GitHubClient()

    def unavailable(*args, **kwargs):
        raise SyncError("offline")

    monkeypatch.setattr(client, "get", unavailable)
    result = client.enrich(source(), {"review": "approved"})
    assert status_label(result) == "状态待更新"


def test_missing_search_item_is_rechecked_to_detect_merge(monkeypatch):
    client = GitHubClient()
    monkeypatch.setattr(client, "search", lambda: [])
    monkeypatch.setattr(client, "get", lambda *a, **k: {"state": "closed", "merged_at": "2026-10-29T13:00:00Z",
                                                        "merged": True, "title": "A fix", "updated_at": "2026-10-29T13:00:00Z"})
    monkeypatch.setattr(client, "repository_info", lambda *args: {"metadata_ok": True, "activity_ok": True})
    snapshot = client.sync({"items": [{"repository": "org/repo", "number": 42, "state": "open", "title": "A fix",
                                     "url": "https://github.com/org/repo/pull/42", "updated_at": "2026-10-29T12:00:00Z"}]})
    assert len(snapshot["items"]) == 1
    assert lifecycle(snapshot["items"][0]) == "merged"


def test_latest_repository_merge_uses_merged_at_across_pages_not_updated_at(monkeypatch):
    client = GitHubClient()
    seen_pages = []
    older = {"number": 1, "merged_at": "2026-10-29T10:00:00Z", "updated_at": "2026-10-29T12:00:00Z"}
    newest = {"number": 2, "merged_at": "2026-10-29T10:30:00Z", "updated_at": "2026-10-29T10:45:00Z",
              "html_url": "https://github.com/org/repo/pull/2"}
    def get(path, **params):
        if path == "/repos/org/repo":
            return {"stargazers_count": 12345}
        if path.endswith("/pulls/2"):
            return {"merged_by": {"login": "maintainer"}}
        seen_pages.append(params["page"])
        return [older] + [{"updated_at": "2026-10-29T11:00:00Z", "merged_at": None}] * 19 if params["page"] == 1 else [newest]
    monkeypatch.setattr(client, "get", get)
    result = client.repository_info("org/repo")
    assert seen_pages == [1, 2]
    assert result["last_merge_at"] == newest["merged_at"]
    assert result["merged_by"] == "maintainer"
    assert result["stars"] == 12345


def test_repository_failure_preserves_values_but_marks_them_stale(monkeypatch):
    client = GitHubClient()
    def fail(*args, **kwargs):
        raise SyncError("offline")
    monkeypatch.setattr(client, "get", fail)
    result = client.repository_info("org/repo", {"stars": 123, "last_merge_at": "2026-10-01T00:00:00Z"})
    assert result["stars"] == 123 and result["last_merge_at"]
    assert not result["metadata_ok"] and not result["activity_ok"]


def test_account_totals_use_issue_search_and_release_asset_downloads(monkeypatch):
    client = GitHubClient()
    seen = []

    def get(path, **params):
        seen.append(path)
        if path == "/search/issues":
            return {"total_count": 12, "incomplete_results": False}
        return [{"assets": [{"download_count": 8}, {"download_count": 2}]}]

    monkeypatch.setattr(client, "get", get)
    assert client.authored_issue_count() == 12
    assert client.repository_downloads("org/repo") == 10
    assert seen == ["/search/issues", "/repos/org/repo/releases"]


def test_own_last_contribution_ignores_maintainer_and_bot_commits(monkeypatch):
    client = GitHubClient()
    item = {"repository": "org/repo", "number": 42, "head_sha": "head", "created_at": "2026-10-29T06:00:00Z"}
    commits = [{"author": {"login": "contributor"}, "committer": {"login": "maintainer"},
                "commit": {"author": {"date": "2026-10-29T07:00:00Z"}, "committer": {"date": "2026-10-29T09:00:00Z"}}},
               {"author": {"login": "bot[bot]"}, "commit": {"author": {"date": "2026-10-29T10:00:00Z"}}}]
    monkeypatch.setattr(client, "pages", lambda *args: commits)
    client.contribution_time(item, {"commits": 2}, None)
    assert item["last_contribution_at"] == "2026-10-29T07:00:00Z"
    assert item["contribution_time_ok"]


def test_unchanged_commit_head_reuses_personal_time_without_recounting(monkeypatch):
    client = GitHubClient()
    def unexpected(*args, **kwargs):
        pytest.fail("Unchanged commit history should use the verified timestamp")
    monkeypatch.setattr(client, "pages", unexpected)
    item = {"head_sha": "same", "created_at": "2026-10-29T06:00:00Z"}
    client.contribution_time(item, {}, {"head_sha": "same", "contribution_time_ok": True,
                                       "last_contribution_at": "2026-10-29T07:00:00Z"})
    assert item["last_contribution_at"] == "2026-10-29T07:00:00Z"


def test_ignored_pr_is_not_fetched_or_restored_from_previous_snapshot(monkeypatch):
    client = GitHubClient()
    ignored_source = dict(source(), repository_url="https://api.github.com/repos/contributor/example-repo", number=1)
    monkeypatch.setattr(client, "search", lambda: [ignored_source])
    monkeypatch.setattr("merge_monitor.github.load_rules", lambda: {
        "account": "contributor", "ignored_prs": ["contributor/example-repo#1"],
        "handled_actions": {}, "repository_categories": {},
    })
    def unexpected(*args, **kwargs):
        pytest.fail("An ignored PR must not be fetched, even when it remains in cache")
    monkeypatch.setattr(client, "enrich", unexpected)
    monkeypatch.setattr(client, "repository_info", unexpected)
    snapshot = client.sync({"items": [{"repository": "contributor/example-repo", "number": 1}]})
    assert snapshot["items"] == [] and snapshot["repositories"] == {}


def test_candidate_info_excludes_pull_requests_and_marks_new_issues(monkeypatch):
    client = GitHubClient()

    def get(path, **params):
        if path == "/repos/org/repo":
            return {"stargazers_count": 9000, "description": "agent research", "topics": ["agent"]}
        return [
            {"number": 2, "title": "Open issue", "html_url": "https://github.com/org/repo/issues/2",
             "state": "open", "created_at": "2026-10-29T10:00:00Z", "updated_at": "2026-10-30T10:00:00Z",
             "comments": 0, "labels": [{"name": "bug"}]},
            {"number": 3, "title": "Already a PR", "pull_request": {}, "state": "open"},
        ]

    monkeypatch.setattr(client, "get", get)
    result = client.candidate_repository_info("org/repo")
    assert result["stars"] == 9000 and result["issues_ok"]
    assert [issue["number"] for issue in result["issues"]] == [2]
    assert result["issues"][0]["new"]
