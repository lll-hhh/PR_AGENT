import json
from pathlib import Path

from merge_monitor.state import attention_signature, contributed_repositories, contribution_ordinal, contribution_totals, display_status, lifecycle, monitored_items, pull_request_key, read_snapshot, repository_summary, review_state, save_snapshot, section, status_label


def pending(**updates):
    return {"state": "open", "draft": False, "details_ok": True, "signals_ok": True, "checks": [], **updates}


def test_candidate_repository_links_are_normalized_and_seed_pool_is_present():
    from merge_monitor.state import bundled_candidates, candidate_repositories, normalize_repository

    assert normalize_repository("https://github.com/org/repo/issues/12") == "org/repo"
    assert normalize_repository("bad value") is None
    assert "langchain-ai/deepagents" in bundled_candidates()
    assert "example/repo" in candidate_repositories({"candidate_repositories": ["example/repo"]})


def test_closed_without_merge_is_never_counted_as_merged():
    assert lifecycle({"state": "closed", "merged_at": None}) == "closed"
    assert lifecycle({"state": "closed", "merged_at": "2026-10-29T12:00:00Z"}) == "merged"
    assert lifecycle({"state": "open", "draft": True}) == "draft"


def test_successful_ai_review_is_not_human_approval():
    reviews = [{"user": {"login": "reviewer[bot]", "type": "Bot"}, "state": "APPROVED"}]
    assert review_state(reviews) == "waiting"
    assert status_label(pending(review="waiting", mergeable_state="blocked")) == "待评审"


def test_latest_decisive_human_review_wins_but_comments_do_not_erase_it():
    reviews = [
        {"user": {"login": "alice"}, "state": "CHANGES_REQUESTED", "submitted_at": "2026-10-01"},
        {"user": {"login": "alice"}, "state": "APPROVED", "submitted_at": "2026-10-02"},
        {"user": {"login": "alice"}, "state": "COMMENTED", "submitted_at": "2026-10-03"},
    ]
    assert review_state(reviews) == "approved"
    reviews.append({"user": {"login": "alice"}, "state": "DISMISSED", "submitted_at": "2026-10-04"})
    assert review_state(reviews) == "waiting"


def test_changes_from_one_reviewer_are_not_hidden_by_another_approval():
    assert review_state([
        {"user": {"login": "a"}, "state": "CHANGES_REQUESTED"},
        {"user": {"login": "b"}, "state": "APPROVED"},
    ]) == "changes"


def test_status_distinguishes_waiting_cla_checks_failure_and_conflict():
    item = pending()
    item["checks"] = [{"name": "license/cla", "status": "queued", "conclusion": None}]
    assert status_label(item) == "待签 CLA"
    item["checks"][0].update(status="completed", conclusion="success")
    assert status_label(item) == "待评审"
    item["checks"].append({"name": "tests", "status": "in_progress"})
    assert status_label(item) == "检查中"
    item["checks"][1].update(status="completed", conclusion="failure")
    assert status_label(item) == "检查未通过"
    item["mergeable"] = False
    assert status_label(item) == "有冲突"


def test_incomplete_checks_never_claim_approval():
    item = pending(review="approved")
    item["signals_ok"] = False
    assert status_label(item) == "状态待更新"


def test_cache_roundtrip_is_atomic_and_rejects_wrong_account(tmp_path):
    path = tmp_path / "new" / "snapshot.json"
    snapshot = {"account": "contributor", "items": [{"number": 662}]}
    save_snapshot(snapshot, path)
    assert read_snapshot(path) == snapshot
    assert not path.with_suffix(".tmp").exists()
    path.write_text(json.dumps({"account": "someone-else", "items": []}))
    assert read_snapshot(path) is None
    path.write_text("broken json")
    assert read_snapshot(path) is None


def test_sections_separate_contributor_actions_from_maintainer_waiting():
    assert section(pending(workflow_approval=True)) == "waiting"
    assert section(pending(review="changes")) == "action"
    assert section(pending(checks=[{"name": "tests", "status": "completed", "conclusion": "failure"}])) == "action"
    assert section(dict(state="open", draft=True)) == "action"
    assert section(dict(state="closed", merged_at=None)) == "action"
    assert section(dict(state="closed", merged_at="2026-10-29T12:00:00Z")) == "merged"


def test_merged_contributions_exclude_open_closed_unmerged_and_draft_diffs():
    common = {"repository": "org/repo", "stats_ok": True, "contribution_time_ok": True}
    items = [dict(common, state="closed", merged=True, additions=20, deletions=3, created_at="2026-10-01T01:00:00Z"),
             dict(common, state="open", additions=100, deletions=50, created_at="2026-10-02T01:00:00Z"),
             dict(common, state="closed", additions=40, deletions=9, created_at="2026-10-03T01:00:00Z"),
             dict(common, state="open", draft=True, additions=999, deletions=999, created_at="2026-10-04T01:00:00Z")]
    result = repository_summary(items, "org/repo", merged_only=True)
    assert (result["count"], result["additions"], result["deletions"]) == (1, 20, 3)
    assert result["submitted_count"] == 3
    assert result["last_contribution_at"] == "2026-10-03T01:00:00Z"
    assert repository_summary(items, "org/repo")["additions"] == 160


def test_missing_merged_diff_is_unknown_instead_of_zero_contributions():
    result = repository_summary([{"repository": "org/repo", "merged": True}], "org/repo", merged_only=True)
    assert result["count"] == 1
    assert not result["stats_ok"]


def test_contribution_order_is_per_repository_across_states_and_skips_drafts():
    items = [{"repository": "a/repo", "number": 30, "state": "open"},
             {"repository": "a/repo", "number": 10, "state": "closed", "merged": True},
             {"repository": "a/repo", "number": 20, "state": "closed"},
             {"repository": "a/repo", "number": 5, "draft": True},
             {"repository": "b/repo", "number": 1, "merged": True}]
    assert [contribution_ordinal(items, i) for i in items] == [3, 1, 2, None, 1]
    items[0].update(state="closed", merged=True)
    assert contribution_ordinal(list(reversed(items)), items[0]) == 3


def test_repository_view_requires_merge_and_deduplicates_accepted_prs():
    items = [{"repository": "a/repo", "number": 1, "merged": True, "merged_at": "2026-10-01T00:00:00Z"},
             {"repository": "a/repo", "number": 2, "merged_at": "2026-10-03T00:00:00Z"},
             {"repository": "b/repo", "number": 1, "created_at": "2026-10-02T00:00:00Z"},
             {"repository": "closed/repo", "number": 1, "state": "closed", "merged_at": None},
             {"repository": "draft/repo", "number": 1, "draft": True}]
    assert contributed_repositories(items) == ["a/repo"]


def test_contribution_totals_use_merged_prs_and_known_repository_metadata():
    items = [{"repository": "a/repo", "number": 1, "merged": True, "commits": 3,
              "stats_ok": True, "additions": 20, "deletions": 4},
             {"repository": "a/repo", "number": 2, "merged": True, "commits": 2,
              "stats_ok": True, "additions": 8, "deletions": 1},
             {"repository": "b/repo", "number": 1, "state": "open", "commits": 99,
              "stats_ok": True, "additions": 500, "deletions": 200}]
    totals = contribution_totals(items, {"a/repo": {"stars": 1200}, "b/repo": {"stars": 9000}}, 7, 42)
    assert totals == {"repositories": 1, "issues": 7, "commits": 5, "commits_ok": True,
                      "additions": 28, "deletions": 5, "lines_ok": True,
                      "merges": 2, "stars": 1200, "stars_ok": True, "downloads": 42}


def test_ignored_pr_does_not_hide_other_contributions_to_same_repository():
    items = [{"repository": "contributor/example-repo", "number": 1, "draft": True},
             {"repository": "contributor/example-repo", "number": 2, "merged": True}]
    result = monitored_items(items, {"ignored_prs": ["contributor/example-repo#1"]})
    assert [i["number"] for i in result] == [2]


def test_acknowledged_failure_waits_without_claiming_ci_success_and_new_failure_returns():
    item = dict(pending(), repository="org/repo", number=1, head_sha="old",
                checks=[{"id": 10, "name": "tests", "status": "completed", "conclusion": "failure", "completed_at": "2026-10-29T10:00:00Z"}])
    rules = {"handled_actions": {pull_request_key(item): {"signature": attention_signature(item)}}}
    handled = monitored_items([item], rules)[0]
    assert section(handled) == "waiting"
    assert display_status(handled) == "已处理 · 等待上游"
    assert status_label(handled) == "检查未通过"
    assert not item.get("action_handled")
    assert section(monitored_items([dict(item, review="approved")], rules)[0]) == "waiting"
    assert section(monitored_items([dict(item, review="changes")], rules)[0]) == "action"
    rerun = dict(item, checks=[dict(item["checks"][0], id=11)])
    assert section(monitored_items([rerun], rules)[0]) == "action"
    assert section(monitored_items([dict(item, head_sha="new")], rules)[0]) == "action"


def test_bundled_merged_pr_is_no_longer_an_action_alert():
    assets = Path(__file__).parents[1] / "merge_monitor" / "assets"
    seed = json.loads((assets / "seed.json").read_text(encoding="utf-8"))
    rules = json.loads((assets / "rules.json").read_text(encoding="utf-8"))
    assert seed["items"] == []
    assert seed["repositories"] == {}
    assert rules["ignored_prs"] == []
    assert rules["handled_actions"] == {}
