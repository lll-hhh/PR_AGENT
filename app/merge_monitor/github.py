"""Read GitHub state without creating comments, changing PRs, or storing credentials."""

from __future__ import annotations

import concurrent.futures
import os
import shutil
import subprocess
import threading

import requests

from .state import ACCOUNT, candidate_repositories, contributed_repositories, is_ignored, lifecycle, load_rules, normalize_repository, review_state, timestamp, utc_now


class SyncError(Exception):
    pass


def existing_credential() -> str | None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    git = shutil.which("git")
    if not git:
        candidate = os.path.join(os.environ.get("ProgramFiles", "C:/Program Files"), "Git", "cmd", "git.exe")
        git = candidate if os.path.isfile(candidate) else None
    if not git:
        return None
    try:
        result = subprocess.run(
            [git, "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never"),
        )
        if result.returncode == 0:
            fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            return fields.get("password")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


class GitHubClient:
    def __init__(self, token: str | None = None, cancelled=None):
        self.token = token
        self.local = threading.local()
        self.cancelled = cancelled or (lambda: False)

    @property
    def authenticated(self) -> bool:
        return bool(self.token)

    def get(self, path: str, **params):
        if self.cancelled():
            raise SyncError("已停止同步")
        if not hasattr(self.local, "session"):
            session = requests.Session()
            session.headers.update({"Accept": "application/vnd.github+json", "User-Agent": "ContributionsMonitor/1.4"})
            if self.token:
                session.headers["Authorization"] = f"Bearer {self.token}"
            self.local.session = session
        try:
            response = self.local.session.get("https://api.github.com" + path, params=params, timeout=(6, 22))
        except requests.RequestException:
            raise SyncError("暂时连接不到 GitHub，已保留上次列表") from None
        if response.status_code in {403, 429}:
            if response.headers.get("X-RateLimit-Remaining") == "0" or response.status_code == 429:
                raise SyncError("GitHub 访问频率已达上限，稍后将自动重试")
            raise SyncError("部分状态暂时无法读取，稍后将自动重试")
        if response.status_code == 401:
            raise SyncError("GitHub 登录已失效，请在 Git 中重新登录")
        if not response.ok:
            raise SyncError("GitHub 暂时无法更新，已保留上次列表")
        try:
            return response.json()
        except ValueError:
            raise SyncError("GitHub 暂时无法更新，已保留上次列表") from None

    def pages(self, path: str, **params) -> list:
        results = []
        for page in range(1, 101):
            data = self.get(path, per_page=100, page=page, **params)
            if not isinstance(data, list):
                raise SyncError("GitHub 返回的数据不完整，已保留上次列表")
            results.extend(data)
            if len(data) < 100:
                return results
        raise SyncError("列表暂时无法完整读取，请稍后重试")

    def search(self) -> list[dict]:
        results = []
        # GitHub search returns at most 1,000 results. Fail visibly instead of
        # silently claiming that a truncated list is the full account history.
        for page in range(1, 11):
            data = self.get("/search/issues", q=f"is:pr author:{ACCOUNT}", sort="updated", order="desc", per_page=100, page=page)
            if data.get("incomplete_results") or data["total_count"] > 1000:
                raise SyncError("GitHub 返回的列表不完整，稍后将自动重试")
            results.extend(data["items"])
            if len(results) >= data["total_count"]:
                return results
        return results

    def enrich(self, source: dict, previous: dict | None) -> dict:
        repo = source["repository_url"].split("/repos/")[-1]
        number = source["number"]
        item = {
            "repository": repo,
            "number": number,
            "title": source["title"],
            "url": source["html_url"],
            "state": source["state"],
            "draft": source.get("draft", False),
            "updated_at": source["updated_at"],
            "created_at": source.get("created_at"),
            "merged_at": source.get("pull_request", {}).get("merged_at"),
            "details_ok": False,
            "signals_ok": False,
        }
        try:
            pr = self.get(f"/repos/{repo}/pulls/{number}")
        except SyncError:
            # Never present an unverified merge state as current information.
            return item
        item.update(
            state=pr["state"], draft=pr.get("draft", False), merged_at=pr.get("merged_at"),
            merged=pr.get("merged", False), mergeable=pr.get("mergeable"), mergeable_state=pr.get("mergeable_state"),
            title=pr["title"], updated_at=pr["updated_at"], details_ok=True,
            created_at=pr.get("created_at") or item.get("created_at"),
            additions=pr.get("additions"), deletions=pr.get("deletions"),
            commits=pr.get("commits") if isinstance(pr.get("commits"), int) else None,
            stats_ok=all(isinstance(pr.get(key), int) for key in ("additions", "deletions")),
            head_sha=(pr.get("head") or {}).get("sha"),
        )
        self.contribution_time(item, pr, previous)
        if lifecycle(item) in {"merged", "closed", "draft"}:
            item["signals_ok"] = True
            return item
        sha = pr["head"]["sha"]
        try:
            reviews = self.pages(f"/repos/{repo}/pulls/{number}/reviews")
            checks = self.get(f"/repos/{repo}/commits/{sha}/check-runs", per_page=100)
            statuses = self.get(f"/repos/{repo}/commits/{sha}/status", per_page=100)
            runs = self.get(f"/repos/{repo}/actions/runs", head_sha=sha, event="pull_request", per_page=100)
            item["review"] = review_state(reviews)
            item["checks"] = [
                {"id": c.get("id"), "name": c["name"], "status": c["status"], "conclusion": c.get("conclusion"),
                 "completed_at": c.get("completed_at")}
                for c in checks["check_runs"]
            ] + [
                {"id": c.get("id"), "name": c["context"], "status": "completed" if c["state"] != "pending" else "queued",
                 "completed_at": c.get("updated_at"),
                 "conclusion": {"success": "success", "failure": "failure", "error": "failure"}.get(c["state"])}
                for c in statuses["statuses"]
            ]
            item["workflow_approval"] = any(
                r.get("status") in {"waiting", "action_required"} or r.get("conclusion") == "action_required"
                for r in runs["workflow_runs"]
            )
            item["signals_ok"] = checks["total_count"] <= 100 and statuses["total_count"] <= 100
        except SyncError:
            item["signals_ok"] = False
        return item

    def contribution_time(self, item: dict, pr: dict, previous: dict | None):
        """Ignore comments, checks, and maintainer commits in the personal date."""
        item["last_contribution_at"] = item.get("created_at")
        item["contribution_time_ok"] = False
        if previous and previous.get("head_sha") == item.get("head_sha") and previous.get("contribution_time_ok"):
            item["last_contribution_at"] = previous.get("last_contribution_at") or item.get("created_at")
            item["contribution_time_ok"] = True
            return
        if not item.get("head_sha"):
            return
        try:
            dates = [item.get("created_at")]
            commits = self.pages(f"/repos/{item['repository']}/pulls/{item['number']}/commits")
            for commit in commits:
                for role in ("author", "committer"):
                    if (commit.get(role) or {}).get("login", "").lower() == ACCOUNT.lower():
                        dates.append((commit.get("commit", {}).get(role) or {}).get("date"))
            item["last_contribution_at"] = max((d for d in dates if d), default=None)
            # This endpoint returns at most 250 commits; mark larger PRs partial.
            item["contribution_time_ok"] = pr.get("commits", len(commits)) <= 250
        except SyncError:
            pass

    def repository_info(self, repository: str, previous: dict | None = None) -> dict:
        result = dict(previous or {})
        result.update(repository=repository, metadata_ok=False, activity_ok=False)
        try:
            metadata = self.get(f"/repos/{repository}")
            result.update(stars=metadata["stargazers_count"], metadata_ok=True,
                          description=metadata.get("description") or "", topics=metadata.get("topics", []))
        except SyncError:
            pass
        try:
            latest = None
            complete = False
            page_size = 20
            # A closed PR's updated_at is >= merged_at. Once the update ordering
            # passes our best merge timestamp, no later page can hide a new merge.
            for page in range(1, 101):
                rows = self.get(f"/repos/{repository}/pulls", state="closed", sort="updated",
                                direction="desc", per_page=page_size, page=page)
                for row in rows:
                    if row.get("merged_at") and (latest is None or row["merged_at"] > latest["merged_at"]):
                        latest = row
                if len(rows) < page_size or (latest and rows[-1]["updated_at"] <= latest["merged_at"]):
                    complete = True
                    break
            if not complete:
                raise SyncError("仓库合并记录暂时无法完整读取")
            result.update(last_merge_at=latest["merged_at"] if latest else None,
                          last_merge_number=latest["number"] if latest else None,
                          last_merge_url=latest.get("html_url") if latest else None,
                          merged_by=None, activity_ok=True)
            if latest:
                detail = self.get(f"/repos/{repository}/pulls/{latest['number']}")
                result["merged_by"] = (detail.get("merged_by") or {}).get("login")
        except SyncError:
            pass
        return result

    def authored_issue_count(self) -> int:
        """Count authored issues without including pull requests."""
        result = self.get("/search/issues", q=f"is:issue author:{ACCOUNT}", per_page=1, page=1)
        if not isinstance(result, dict):
            raise SyncError("Issue 统计暂时不完整")
        if result.get("incomplete_results"):
            raise SyncError("Issue 统计暂时不完整")
        total = result.get("total_count")
        if not isinstance(total, int) or total < 0:
            raise SyncError("Issue 统计暂时不完整")
        return total

    def repository_downloads(self, repository: str) -> int:
        """Sum GitHub release asset download counters for a repository."""
        total = 0
        for release in self.pages(f"/repos/{repository}/releases"):
            if not isinstance(release, dict):
                raise SyncError("下载统计暂时不完整")
            assets = release.get("assets", [])
            if not isinstance(assets, list):
                raise SyncError("下载统计暂时不完整")
            total += sum(asset.get("download_count", 0) for asset in assets
                         if isinstance(asset, dict) and isinstance(asset.get("download_count", 0), int))
        return total

    def candidate_repository_info(self, repository: str, previous: dict | None = None) -> dict:
        """Read lightweight metadata and open, non-PR issues for a candidate repository."""
        result = dict(previous or {})
        result.update(repository=repository, metadata_ok=False, issues_ok=False)
        try:
            metadata = self.get(f"/repos/{repository}")
            if not isinstance(metadata, dict) or not isinstance(metadata.get("stargazers_count"), int):
                return result
            result.update(stars=metadata["stargazers_count"], description=metadata.get("description") or "",
                          topics=metadata.get("topics", []), metadata_ok=True)
        except SyncError:
            return result
        try:
            rows = self.get(f"/repos/{repository}/issues", state="open", sort="updated", direction="desc", per_page=50, page=1)
            if not isinstance(rows, list):
                raise SyncError("候选 Issue 列表暂时无法读取")
            previous_issues = {row.get("number"): row for row in (previous or {}).get("issues", [])}
            checked_at = utc_now()
            issues = []
            for row in rows:
                # GitHub's issues endpoint also returns pull requests. They are
                # deliberately excluded: this column is for unresolved issues.
                if "pull_request" in row or not row.get("number"):
                    continue
                old = previous_issues.get(row["number"], {})
                issues.append({
                    "number": row["number"], "title": row.get("title", ""),
                    "url": row.get("html_url") or f"https://github.com/{repository}/issues/{row['number']}",
                    "state": row.get("state", "open"), "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"), "comments": row.get("comments", 0),
                    "labels": [label.get("name", "") for label in row.get("labels", []) if label.get("name")],
                    "new": not old,
                })
            result.update(issues=issues, issues_checked_at=checked_at, issues_ok=True)
        except SyncError:
            pass
        return result

    def later_merge_info(self, repository: str, items: list[dict], previous: dict | None = None) -> dict:
        result = {key: value for key, value in (previous or {}).items() if key.startswith("later_merges")}
        result["later_merges_ok"] = False
        pending = [item for item in items if lifecycle(item) == "pending"]
        if not pending:
            return {"later_merges_ok": True, "later_merges": [], "later_merges_since": None,
                    "later_merges_checked_at": utc_now()}
        dates = [timestamp(item.get("created_at")) for item in pending]
        if any(date is None for date in dates) or any(not item.get("details_ok") for item in pending):
            return result
        since = min(dates)
        found = {}
        try:
            for page in range(1, 101):
                # Creation order gives a safe stopping point. Recent comments
                # on old merged PRs must not be mistaken for later submissions.
                rows = self.get(f"/repos/{repository}/pulls", state="closed", sort="created",
                                direction="desc", per_page=100, page=page)
                if not isinstance(rows, list):
                    raise SyncError("仓库合并顺序暂时无法完整读取")
                reached_start = False
                for row in rows:
                    created = timestamp(row.get("created_at"))
                    if created is None:
                        raise SyncError("仓库合并顺序暂时无法完整读取")
                    if created <= since:
                        reached_start = True
                        continue
                    merged = timestamp(row.get("merged_at"))
                    author = (row.get("user") or {}).get("login", "")
                    if merged and merged >= created and author.lower() != ACCOUNT.lower():
                        found[row["number"]] = {
                            "number": row["number"], "title": row.get("title", ""),
                            "url": row.get("html_url") or f"https://github.com/{repository}/pull/{row['number']}",
                            "author": author, "created_at": row["created_at"], "merged_at": row["merged_at"],
                        }
                if reached_start or len(rows) < 100:
                    result.update(later_merges_ok=True, later_merges_since=since.isoformat(),
                                  later_merges=sorted(found.values(), key=lambda row: timestamp(row["merged_at"]), reverse=True),
                                  later_merges_checked_at=utc_now())
                    return result
        except SyncError:
            return result
        return result

    def sync(self, previous: dict | None = None) -> dict:
        rules = load_rules()
        sources = [source for source in self.search() if not is_ignored(
            {"repository": source["repository_url"].split("/repos/")[-1], "number": source["number"]}, rules)]
        prior = {(i["repository"], i["number"]): i for i in (previous or {}).get("items", []) if not is_ignored(i, rules)}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self.enrich, source, prior.get((source["repository_url"].split("/repos/")[-1], source["number"]))) for source in sources]
            items = [future.result() for future in futures]
        # Search indexing may lag. Keep monitoring previously seen PRs even if
        # GitHub omits one from a subsequent search response.
        seen = {(i["repository"], i["number"]) for i in items}
        for key, old in prior.items():
            if key not in seen:
                source = {"repository_url": "https://api.github.com/repos/" + old["repository"], "number": old["number"],
                          "title": old["title"], "html_url": old["url"], "state": old["state"], "draft": old.get("draft", False),
                          "updated_at": old["updated_at"], "pull_request": {"merged_at": old.get("merged_at")}}
                items.append(self.enrich(source, old))
        items.sort(key=lambda i: i.get("updated_at") or "", reverse=True)
        previous_repositories = (previous or {}).get("repositories", {})
        names = sorted({i["repository"] for i in items})
        def repository_status(name):
            old = previous_repositories.get(name)
            result = self.repository_info(name, old)
            result.update(self.later_merge_info(name, [i for i in items if i["repository"] == name], old))
            return result
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            repositories = dict(zip(names, pool.map(repository_status, names)))
        # Candidate repositories are user-curated and kept separate from the
        # contribution history. An absent field keeps old snapshots compatible.
        # A seeded desktop snapshot opts into candidate scanning. Keeping the
        # field optional preserves the lightweight client contract for callers
        # that only want contribution history.
        candidate_names = candidate_repositories(previous) if "candidate_repositories" in (previous or {}) else []
        previous_candidates = (previous or {}).get("candidates", {})
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            candidate_values = list(pool.map(
                lambda name: self.candidate_repository_info(name, previous_candidates.get(name)), candidate_names))
        candidates = {value["repository"]: value for value in candidate_values}
        previous_totals = (previous or {}).get("contribution_totals", {})
        issue_count = previous_totals.get("issues")
        issues_ok = False
        try:
            issue_count = self.authored_issue_count()
            issues_ok = True
        except SyncError:
            pass
        contributed = contributed_repositories(items)
        downloads = previous_totals.get("downloads")
        downloads_ok = False
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                downloads = sum(pool.map(self.repository_downloads, contributed))
            downloads_ok = True
        except SyncError:
            pass
        from .state import contribution_totals
        totals = contribution_totals(items, repositories, issue_count, downloads)
        totals.update(issues_ok=issues_ok, downloads_ok=downloads_ok)
        return {"account": ACCOUNT, "updated_at": utc_now(), "items": items, "repositories": repositories,
                "candidate_repositories": (previous or {}).get("candidate_repositories", []),
                "candidates": candidates,
                "contribution_totals": totals,
                "partial": any(not i.get("details_ok") or not i.get("signals_ok") or not i.get("stats_ok") for i in items)
                           or any(not r.get("metadata_ok") or not r.get("activity_ok") or not r.get("later_merges_ok")
                                  for r in repositories.values()) or any(not r.get("metadata_ok") or not r.get("issues_ok")
                                                                         for r in candidates.values())
                           or not issues_ok or not downloads_ok}
