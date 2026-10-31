"""PR lifecycle and review status, kept independent from the desktop UI."""

from __future__ import annotations

import json
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path

ACCOUNT = os.environ.get("PR_MONITOR_ACCOUNT", "contributor")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def lifecycle(item: dict) -> str:
    if item.get("merged_at") or item.get("merged"):
        return "merged"
    if item.get("state") == "closed":
        return "closed"
    if item.get("draft"):
        return "draft"
    return "pending"


def review_state(reviews: list[dict]) -> str:
    """Use each human reviewer's latest decisive review; ignore bot approvals."""
    latest = {}
    for review in sorted(reviews, key=lambda value: value.get("submitted_at") or ""):
        user = review.get("user") or {}
        login = user.get("login", "")
        if not login or user.get("type") == "Bot" or login.endswith("[bot]"):
            continue
        state = review.get("state")
        if state in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[login] = state
    if "CHANGES_REQUESTED" in latest.values():
        return "changes"
    if "APPROVED" in latest.values():
        return "approved"
    return "waiting"


def status_label(item: dict) -> str:
    phase = lifecycle(item)
    if phase != "pending":
        return {"merged": "已合并", "closed": "已关闭", "draft": "草稿"}[phase]
    if not item.get("details_ok", False):
        return "状态待更新"
    if item.get("mergeable_state") == "dirty" or item.get("mergeable") is False:
        return "有冲突"
    if item.get("review") == "changes":
        return "需修改"
    checks = item.get("checks", [])
    unsuccessful = {"failure", "timed_out", "cancelled", "action_required", "stale"}
    cla_checks = [c for c in checks if "cla" in c.get("name", "").lower().replace("classifier", "")]
    if any(c.get("conclusion") not in {"success", "neutral", "skipped"} for c in cla_checks):
        return "待签 CLA"
    if any(c.get("conclusion") in unsuccessful for c in checks):
        return "检查未通过"
    if item.get("workflow_approval"):
        return "待批准检查"
    if any(c.get("status") != "completed" for c in checks):
        return "检查中"
    if not item.get("signals_ok", False):
        return "状态待更新"
    if item.get("review") == "approved":
        return "已获批准"
    return "待评审"


SECTIONS = {"waiting": "等待合并", "action": "待处理", "merged": "已合并"}
VIEWS = {**SECTIONS, "repositories": "已贡献仓库", "candidates": "候选仓库"}


def section(item: dict) -> str:
    """Separate actions the contributor can take from waiting on maintainers."""
    if lifecycle(item) == "merged":
        return "merged"
    if lifecycle(item) in {"draft", "closed"}:
        return "action"
    if item.get("action_handled") and item.get("details_ok") and item.get("signals_ok"):
        return "waiting"
    if status_label(item) in {"有冲突", "需修改", "待签 CLA", "检查未通过", "状态待更新"}:
        return "action"
    return "waiting"


def repository_summary(items: list[dict], repository: str, *, merged_only: bool = False) -> dict:
    """Count each submitted PR once, using its current diff, never commit sums."""
    submitted = [i for i in items if i["repository"] == repository and not i.get("draft")]
    merged = [i for i in submitted if lifecycle(i) == "merged"]
    selected = merged if merged_only else submitted
    known = [i for i in selected if i.get("stats_ok")]
    times = [i.get("last_contribution_at") or i.get("created_at") for i in submitted]
    return {
        "count": len(selected), "merged_count": len(merged), "submitted_count": len(submitted),
        "additions": sum(i["additions"] for i in known),
        "deletions": sum(i["deletions"] for i in known),
        "stats_ok": len(known) == len(selected),
        "last_contribution_at": max((t for t in times if t), default=None),
        "contribution_time_ok": all(i.get("contribution_time_ok") for i in submitted),
    }


def contribution_ordinal(items: list[dict], item: dict) -> int | None:
    """PR numbers preserve creation order within a repository, across states."""
    if item.get("draft"):
        return None
    numbers = sorted({i["number"] for i in items
                      if i["repository"] == item["repository"] and not i.get("draft")})
    try:
        return numbers.index(item["number"]) + 1
    except ValueError:
        return None


def contributed_repositories(items: list[dict]) -> list[str]:
    """Only accepted contributions qualify a repository for this view."""
    latest = {}
    for item in items:
        if lifecycle(item) == "merged":
            name = item["repository"]
            stamp = item.get("merged_at") or item.get("last_contribution_at") or ""
            latest[name] = max(latest.get(name, ""), stamp)
    return sorted(latest, key=lambda name: (latest[name], name), reverse=True)


def contribution_totals(items: list[dict], repositories: dict, issue_count: int | None,
                        downloads: int | None) -> dict:
    """Summarize accepted PR contributions across distinct repositories."""
    names = contributed_repositories(items)
    merged = [item for item in items if lifecycle(item) == "merged"]
    merged_known = [item for item in merged if isinstance(item.get("commits"), int)]
    line_stats = [item for item in merged if item.get("stats_ok")]
    stars_known = [repositories.get(name, {}).get("stars") for name in names]
    stars_known = [value for value in stars_known if isinstance(value, int)]
    return {
        "repositories": len(names), "issues": issue_count,
        "commits": sum(item["commits"] for item in merged_known),
        "commits_ok": len(merged_known) == len(merged),
        "additions": sum(item["additions"] for item in line_stats),
        "deletions": sum(item["deletions"] for item in line_stats),
        "lines_ok": len(line_stats) == len(merged),
        "merges": len(merged), "stars": sum(stars_known),
        "stars_ok": len(stars_known) == len(names), "downloads": downloads,
    }


def pull_request_key(item: dict) -> str:
    return f"{item['repository'].lower()}#{item['number']}"


def load_rules() -> dict:
    rules = {"account": ACCOUNT, "ignored_prs": [], "handled_actions": {}, "repository_categories": {}}
    for path in (Path(__file__).parent / "assets" / "rules.json", cache_path().with_name("rules.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("account") != ACCOUNT:
                continue
            rules["ignored_prs"] = sorted(set(rules["ignored_prs"]) | set(value.get("ignored_prs", [])))
            for field in ("handled_actions", "repository_categories"):
                rules[field].update(value.get(field, {}))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return rules


def is_ignored(item: dict, rules: dict) -> bool:
    return pull_request_key(item) in {key.lower() for key in rules.get("ignored_prs", [])}


def attention_signature(item: dict) -> str:
    failed = [{key: check.get(key) for key in ("id", "name", "conclusion", "completed_at")}
              for check in item.get("checks", [])
              if check.get("conclusion") in {"failure", "timed_out", "cancelled", "action_required", "stale"}]
    value = {"head_sha": item.get("head_sha"), "reason": status_label(item),
             "checks": sorted(failed, key=lambda check: (check.get("name") or "", str(check.get("id"))))}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def monitored_items(items: list[dict], rules: dict) -> list[dict]:
    result = []
    for source in items:
        if is_ignored(source, rules):
            continue
        item = dict(source)
        handled = rules.get("handled_actions", {}).get(pull_request_key(item), {})
        item["action_handled"] = bool(handled.get("signature") == attention_signature(item))
        result.append(item)
    return result


def display_status(item: dict) -> str:
    return "已处理 · 等待上游" if item.get("action_handled") and section(item) == "waiting" else status_label(item)


def timestamp(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def later_merge_summary(item: dict, info: dict) -> dict:
    """Report observable merge order, without inferring reviewer intent."""
    created = timestamp(item.get("created_at"))
    since = timestamp(info.get("later_merges_since"))
    active = lifecycle(item) == "pending"
    known = bool(active and item.get("details_ok") and created and since and
                 since <= created and info.get("later_merges_ok"))
    matches = {}
    if active and created:
        for row in info.get("later_merges", []):
            submitted = timestamp(row.get("created_at"))
            merged = timestamp(row.get("merged_at"))
            if (submitted and merged and submitted > created and merged >= submitted and
                    row.get("number") != item.get("number") and
                    row.get("author", "").lower() != ACCOUNT.lower()):
                matches[row["number"]] = row
    ordered = sorted(matches.values(), key=lambda row: timestamp(row["merged_at"]), reverse=True)
    return {"active": active, "known": known, "matches": ordered,
            "count": len(ordered) if known else None,
            "latest": ordered[0] if ordered else None,
            "checked_at": info.get("later_merges_checked_at")}


def cache_path() -> Path:
    parent = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return parent / "MergeMonitor" / "snapshot-v3.json"


def normalize_repository(value: str) -> str | None:
    """Turn a GitHub repository URL or owner/name into a safe repository key."""
    value = (value or "").strip().rstrip("/")
    if value.startswith("https://github.com/"):
        value = value[len("https://github.com/"):]
    elif value.startswith("http://github.com/"):
        value = value[len("http://github.com/"):]
    parts = value.split("/")
    if len(parts) < 2 or not all(parts[:2]) or any(part in {".", ".."} for part in parts[:2]):
        return None
    owner, repo = parts[:2]
    if any(ch.isspace() for ch in owner + repo) or any(ch in owner + repo for ch in "?#"):
        return None
    return f"{owner}/{repo.removesuffix('.git')}"


def bundled_candidates() -> list[str]:
    """Return the curated algorithm-focused seed pool shipped with the app."""
    try:
        value = json.loads((Path(__file__).parent / "assets" / "candidates.json").read_text(encoding="utf-8"))
        rows = value.get("repositories", [])
        return sorted({repo for row in rows if isinstance(row, dict)
                       for repo in [normalize_repository(row.get("repository", ""))] if repo})
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def candidate_repositories(snapshot: dict | None) -> list[str]:
    """Merge the shipped pool with user-added repositories, preserving keys."""
    rows = (snapshot or {}).get("candidate_repositories", [])
    names = set(bundled_candidates())
    if isinstance(rows, dict):
        rows = rows.keys()
    for row in rows:
        value = row.get("repository") if isinstance(row, dict) else row
        repo = normalize_repository(value or "")
        if repo:
            names.add(repo)
    return sorted(names, key=str.lower)


def read_snapshot(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("account") == ACCOUNT and isinstance(value.get("items"), list):
            return value
    except (OSError, ValueError, AttributeError):
        pass
    return None


def save_snapshot(snapshot: dict, path: Path | None = None) -> None:
    path = path or cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
