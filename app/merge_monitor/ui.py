"""Minimal monochrome desktop interface."""

from __future__ import annotations

import ctypes
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPalette, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QInputDialog, QMainWindow,
    QPushButton, QScrollArea, QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .github import GitHubClient, SyncError, existing_credential
from .catalog import CATEGORY_TREE, classify_repository
from .state import VIEWS, cache_path, candidate_repositories, contributed_repositories, contribution_ordinal, contribution_totals, display_status, later_merge_summary, load_rules, monitored_items, normalize_repository, read_snapshot, repository_summary, save_snapshot, section, status_label, utc_now

ASSETS = Path(__file__).parent / "assets"

STYLE = """
QWidget { color: #ededed; background: #090909; font-family: 'Microsoft YaHei UI'; font-size: 12px; }
QMainWindow { background: #090909; }
QLabel { background: transparent; border: none; }
QPushButton { background: transparent; border: 1px solid #303030; border-radius: 7px; padding: 7px 12px; }
QPushButton:hover { background: #1b1b1b; border-color: #555555; }
QPushButton:disabled { color: #666666; }
QPushButton#tab { color: #737373; border: none; border-bottom: 2px solid transparent; border-radius: 0; font-size: 18px; padding: 14px 0; }
QPushButton#tab:hover { color: #cccccc; }
QPushButton#tab:checked { color: #ffffff; border-bottom-color: #eeeeee; }
QFrame#divider { background: #252525; border: none; min-height: 1px; max-height: 1px; }
QFrame#card { background: #101010; border: 1px solid #272727; border-radius: 9px; }
QFrame#card QLabel, QFrame#card QWidget { background: transparent; }
QLabel#repo { color: #efefef; font-family: 'Bahnschrift'; font-size: 16px; }
QLabel#owner { color: #6f6f6f; font-family: 'Bahnschrift'; font-size: 10px; }
QLabel#prTitle { color: #c1c1c1; font-family: 'Segoe UI'; font-size: 12px; }
QLabel#prTitle:hover { color: #ffffff; }
QLabel#status { color: #aaaaaa; font-size: 11px; }
QLabel#stars { color: #d4d4d4; font-family: 'Bahnschrift'; font-size: 14px; }
QLabel#metricCaption { color: #686868; font-size: 10px; }
QLabel#metricValue { color: #d2d2d2; font-family: 'Segoe UI'; font-size: 13px; }
QLabel#totalValue { color: #eeeeee; font-family: 'Bahnschrift'; font-size: 19px; }
QLabel#footer { color: #797979; font-size: 10px; }
QLabel#emptyTitle { font-size: 18px; color: #bdbdbd; }
QLabel#emptyHint { color: #666666; font-size: 12px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #090909; width: 5px; margin: 0; }
QScrollBar::handle:vertical { background: #383838; min-height: 30px; border-radius: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { color: #ededed; background: #202020; border: 1px solid #444444; padding: 7px; }
QComboBox { color: #d2d2d2; background: #111111; border: 1px solid #303030; border-radius: 6px; padding: 5px 9px; min-height: 18px; }
QComboBox:hover { border-color: #555555; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { color: #ededed; background: #161616; selection-background-color: #303030; border: 1px solid #444444; }
QTreeWidget { background: #0e0e0e; border: 1px solid #252525; border-radius: 8px; padding: 8px 4px; outline: 0; }
QTreeWidget::item { height: 30px; padding: 2px 4px; color: #888888; }
QTreeWidget::item:hover { background: #181818; color: #dddddd; }
QTreeWidget::item:selected { background: #262626; color: #eeeeee; border-radius: 4px; }
"""


def label(text: str, name: str, parent=None) -> QLabel:
    widget = QLabel(text, parent)
    widget.setObjectName(name)
    return widget


def date_text(value: str | None) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%Y/%m/%d %H:%M")
    except (AttributeError, ValueError):
        return "—"


def wait_duration_text(start_value: str | None, end_value: str | None = None, *, now: datetime | None = None) -> str:
    """Format the elapsed time between PR creation and merge/current time."""
    try:
        start = datetime.fromisoformat(start_value.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_value.replace("Z", "+00:00")) if end_value else (now or datetime.now(timezone.utc))
    except (AttributeError, TypeError, ValueError):
        return "待更新"
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    seconds = max(0, int((end - start).total_seconds()))
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}天 {hours}小时"
    if hours:
        return f"{hours}小时 {minutes}分"
    if minutes:
        return f"{minutes}分 {seconds}秒"
    return f"{seconds}秒"


def wait_duration_seconds(item: dict, *, now: datetime | None = None) -> int | None:
    """Return PR wait time in seconds for sorting, or None when timestamps are incomplete."""
    try:
        start = datetime.fromisoformat(item.get("created_at").replace("Z", "+00:00"))
        finish_value = item.get("merged_at")
        finish = datetime.fromisoformat(finish_value.replace("Z", "+00:00")) if finish_value else (now or datetime.now(timezone.utc))
    except (AttributeError, TypeError, ValueError):
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if finish.tzinfo is None:
        finish = finish.replace(tzinfo=timezone.utc)
    return max(0, int((finish - start).total_seconds()))


class SyncWorker(QThread):
    received = Signal(dict, bool)
    failed = Signal(str)

    def __init__(self, previous: dict | None, parent=None):
        super().__init__(parent)
        self.previous = previous

    def run(self):
        try:
            client = GitHubClient(existing_credential(), self.isInterruptionRequested)
            self.received.emit(client.sync(self.previous), client.authenticated)
        except SyncError as error:
            self.failed.emit(str(error))
        except Exception:
            self.failed.emit("暂时无法更新，已保留上次列表")


class LinkLabel(QLabel):
    def __init__(self, text: str, url: str, name: str, parent=None):
        super().__init__(text, parent)
        self.url = url
        self.full_text = text
        self.setObjectName(name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(text)
        self.setMinimumWidth(20)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.setFont(self.font())
        text = self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideRight, self.contentsRect().width())
        painter.drawText(self.contentsRect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    def open_link(self):
        if self.url.startswith("https://github.com/"):
            QDesktopServices.openUrl(QUrl(self.url))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_link()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.open_link()
        else:
            super().keyPressEvent(event)


class ContributionCard(QFrame):
    def __init__(self, repository: str, info: dict, *, item: dict | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.repository = repository
        self.metrics = {}
        self.pr_links = []
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(18, 12, 18, 12)
        self.outer.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(20)
        project = QVBoxLayout()
        project.setSpacing(3)
        owner, name = repository.split("/", 1)
        project_link = LinkLabel(name, "https://github.com/" + repository, "repo")
        project_link.setFixedWidth(165)
        project_link.setToolTip(repository)
        project.addWidget(project_link)
        owner_label = label(owner, "owner")
        owner_label.setFixedWidth(165)
        owner_label.setToolTip(owner)
        owner_label.setText(owner_label.fontMetrics().elidedText(owner, Qt.TextElideMode.ElideRight, 165))
        project.addWidget(owner_label)
        top.addLayout(project)
        if item:
            link = LinkLabel(f"#{item['number']}  {item['title']}", item['url'], "prTitle")
            link.setAccessibleName(f"{repository} #{item['number']} {item['title']}")
            top.addWidget(link, 1)
            status = label(display_status(item), "status")
            note = "本次提醒已处理；GitHub 检查的实际状态如下。\n" if item.get("action_handled") else ""
            status.setToolTip(note + "\n".join(c['name'] + ': ' + str(c.get('conclusion') or c.get('status')) for c in item.get('checks', [])))
            top.addWidget(status)
            self.pr_links.append(link)
        else:
            top.addStretch(1)
        stars = info.get("stars")
        star_text = f"★ {stars:,}" if isinstance(stars, int) else "★ —"
        if stars is not None and not info.get("metadata_ok"):
            star_text += " · 旧"
        star_label = label(star_text, "stars")
        star_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        star_label.setToolTip("GitHub star 数" if info.get("metadata_ok") else "star 数待更新")
        top.addWidget(star_label)
        self.outer.addLayout(top)

    def add_metric(self, layout, caption: str, text: str, tooltip: str, url: str | None = None):
        column = QVBoxLayout()
        column.setSpacing(4)
        column.addWidget(label(caption, "metricCaption"))
        value = LinkLabel(text, url, "metricValue") if url else label(text, "metricValue")
        value.setToolTip(tooltip)
        column.addWidget(value)
        layout.addLayout(column, 1)
        self.metrics[caption] = value


class RepositoryCard(ContributionCard):
    def __init__(self, repository: str, all_items: list[dict], info: dict, parent=None):
        super().__init__(repository, info, parent=parent)
        self.summary = repository_summary(all_items, repository, merged_only=True)
        metrics = QHBoxLayout()
        metrics.setSpacing(20)
        merge_time = date_text(info.get("last_merge_at")) if info.get("last_merge_at") else ("暂无记录" if info.get("activity_ok") else "—")
        if info.get("last_merge_at") and not info.get("activity_ok"):
            merge_time += " · 旧"
        merge_note = "仓库最近一条已合并 PR 的实际合并时间"
        if info.get("last_merge_number"):
            merge_note += f"\n#{info['last_merge_number']} · 操作者 {info.get('merged_by') or '未获取'}"
        self.add_metric(metrics, "仓库最近合并", merge_time, merge_note, info.get("last_merge_url"))
        summary = self.summary
        self.add_metric(metrics, "我最近贡献", date_text(summary["last_contribution_at"]),
                    "最近提交 PR 或本人提交代码的时间；不含评论、机器人和其他人的提交。" +
                    ("\n部分提交记录待更新，当前显示已知时间。" if not summary['contribution_time_ok'] else ""))
        scope = "已合并的 PR"
        lines = f"+{summary['additions']:,} / −{summary['deletions']:,}" if summary['stats_ok'] else "待更新"
        self.add_metric(metrics, "累计贡献行数", lines,
                    f"统计范围：{scope}。\n新增 / 删除行数，按每个 PR 当前差异累计；重复修改不去重。")
        self.add_metric(metrics, "累计贡献次数", f"{summary['count']:,} 次", 
                    f"统计范围：{scope}，每个 PR 记 1 次。\n共提交 {summary['submitted_count']} 次，已合并 {summary['merged_count']} 次。")
        self.outer.addLayout(metrics)


class PullRequestCard(ContributionCard):
    def __init__(self, item: dict, all_items: list[dict], info: dict, parent=None):
        super().__init__(item["repository"], info, item=item, parent=parent)
        self.item = item
        self.ordinal = contribution_ordinal(all_items, item)
        metrics = QHBoxLayout()
        metrics.setSpacing(20)
        lines = f"+{item['additions']:,} / −{item['deletions']:,}" if item.get("stats_ok") else "待更新"
        self.add_metric(metrics, "本次贡献行数", lines, "当前这一个 PR 的新增 / 删除行数，包含尚未合并的改动。")
        sequence = f"第 {self.ordinal} 次" if self.ordinal else ("草稿 · 未计次" if item.get("draft") else "待更新")
        self.add_metric(metrics, "贡献序号", sequence,
                        "你向这个仓库提交的第几个非草稿 PR，按 PR 创建顺序排列。\n等待合并和未合并关闭的 PR 也有序号；草稿不计次。仓库累计贡献只计已合并。")
        if section(item) == "merged":
            self.add_metric(metrics, "总等待时长", wait_duration_text(item.get("created_at"), item.get("merged_at")),
                            "从 PR 创建到实际合并的总等待时长；缺少创建或合并时间时显示待更新。")
        elif section(item) == "waiting":
            self.add_metric(metrics, "已等待", wait_duration_text(item.get("created_at")),
                            "从 PR 创建到现在的等待时长；按 GitHub 的 created_at 计算。")
        self.merge_order = later_merge_summary(item, info)
        order = self.merge_order
        if order["active"]:
            latest = order["latest"]
            if latest:
                prefix = f"{order['count']} 个" if order["known"] else f"至少 {len(order['matches'])} 个 · 旧"
                text = f"{prefix} · #{latest['number']}"
            else:
                text = "暂未发现" if order["known"] else "待更新"
            note = "同仓库中，比本 PR 更晚创建、已经合并的其他人的 PR（含机器人）。\n仅比较提交与合并时间，不表示维护者承诺按顺序处理。"
            if not order["known"]:
                note += "\n当前记录不完整或待更新；历史记录不能当作实时结果。"
            if order["checked_at"]:
                note += "\n最近完整检查：" + date_text(order["checked_at"])
            for row in order["matches"][:20]:
                note += f"\n#{row['number']} · {row.get('author') or '未知作者'} · {row.get('title', '')}\n提交 {date_text(row['created_at'])} → 合并 {date_text(row['merged_at'])}"
            if len(order["matches"]) > 20:
                note += f"\n另有 {len(order['matches']) - 20} 条；点击可进入最近一条。"
            self.add_metric(metrics, "后提交先合并", text, note, latest["url"] if latest else None)
            if latest:
                self.add_metric(metrics, "最近先合并时间", date_text(latest["merged_at"]) + (" · 旧" if not order["known"] else ""),
                                note, latest["url"])
        self.outer.addLayout(metrics)


class CandidateCard(ContributionCard):
    """Compact candidate summary with issue counts for triage."""

    def __init__(self, repository: str, info: dict, category: tuple[str, str] | None = None, parent=None):
        super().__init__(repository, info, parent=parent)
        issues = info.get("issues", []) if isinstance(info.get("issues"), list) else []
        metrics = QHBoxLayout()
        metrics.setSpacing(20)
        if category:
            self.add_metric(metrics, "类型", f"{category[0]} / {category[1]}", "候选仓库的算法方向分类。")
        known = info.get("issues_ok") is True
        fresh = sum(bool(issue.get("new")) for issue in issues)
        stale_suffix = " · 旧" if issues and not known else ""
        self.add_metric(metrics, "新 Issue", f"{fresh:,} 个" if known else (f"{fresh:,} 个 · 旧" if issues else "待更新"),
                        "自上次完整同步后发现的开放 Issue；仅显示汇总数量。")
        self.add_metric(metrics, "开放 Issue", f"{len(issues):,} 个" if known else (f"{len(issues):,} 个 · 旧" if issues else "待更新"),
                        "仓库当前公开的普通开放 Issue，不包含 Pull Request。")
        latest = max((issue.get("updated_at") or issue.get("created_at") or "" for issue in issues), default=None)
        latest_text = date_text(latest) if latest else ("暂无" if known else "待更新")
        self.add_metric(metrics, "最近 Issue 更新", latest_text + stale_suffix, "开放 Issue 中最近一次更新时间。")
        self.outer.addLayout(metrics)
        if info.get("description"):
            description = label(info["description"], "status")
            description.setWordWrap(True)
            self.outer.addWidget(description)


class MainWindow(QMainWindow):
    def __init__(self, *, offline: bool = False):
        super().__init__()
        self.offline = offline
        self.snapshot = read_snapshot(cache_path()) or read_snapshot(ASSETS / "seed.json")
        self.worker = None
        self.last_attempt = 0.0
        self.active_filter = "waiting"
        self.category_filter = (None, None)
        self.authenticated = False
        self.live = False
        self.setWindowTitle("贡献记录")
        self.setWindowIcon(QIcon(str(ASSETS / "merge.ico")))
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1120, screen.width() - 60), min(900, screen.height() - 70))
        self.setMinimumSize(900, 650)
        self.setStyleSheet(STYLE)
        self._build()
        self.render()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        for key in (QKeySequence("F5"), QKeySequence("Ctrl+R")):
            QShortcut(key, self, self.refresh)
        if not offline:
            QTimer.singleShot(100, self.refresh)
        else:
            self.footer.setText("上次记录 · " + date_text((self.snapshot or {}).get("updated_at")))

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(26, 10, 26, 14)
        outer.setSpacing(0)
        tabs = QHBoxLayout()
        tabs.setSpacing(24)
        self.tabs = {}
        for key, text in VIEWS.items():
            button = QPushButton(text)
            button.setObjectName("tab")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, phase=key: self.set_filter(phase))
            tabs.addWidget(button, 1)
            self.tabs[key] = button
        self.tabs["action"].setToolTip("检查失败、冲突、需修改、CLA、草稿、未合并关闭，或状态待更新")
        self.tabs["waiting"].setToolTip("等待评审、检查运行或维护者批准；数量按 PR 统计")
        self.tabs["repositories"].setToolTip("至少合并过你一个 PR 的仓库；按类别和小类查看")
        self.tabs["candidates"].setToolTip("算法向候选仓库；按类别和小类查看")
        outer.addLayout(tabs)
        outer.addSpacing(17)
        self._build_controls(outer)
        outer.addSpacing(10)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.list_widget)
        self.rows_layout.setContentsMargins(0, 0, 6, 0)
        self.rows_layout.setSpacing(10)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.totals_widget = QWidget()
        totals_layout = QHBoxLayout(self.totals_widget)
        totals_layout.setContentsMargins(2, 4, 2, 10)
        totals_layout.setSpacing(10)
        self.total_values = {}
        for key, title in (("repositories", "总仓库"), ("issues", "总 Issue"), ("commits", "总 Commit"),
                           ("merges", "总 Merge"), ("lines", "累计贡献行数"),
                           ("stars", "累计 Star"), ("downloads", "累计下载")):
            column = QVBoxLayout()
            column.setSpacing(3)
            caption = label(title, "metricCaption")
            value = label("待更新", "totalValue")
            value.setToolTip({"repositories": "至少有一个 PR 已合并的仓库数",
                              "issues": "账号创建的普通 Issue，不含 Pull Request",
                              "commits": "已合并 PR 中的 commit 总数",
                              "merges": "已合并的个人 PR 数",
                              "lines": "所有已合并 PR 的新增 / 删除行数之和；重复修改不去重",
                              "stars": "已贡献仓库当前 star 数之和",
                              "downloads": "已贡献仓库 GitHub Release 资产下载量之和"}[key])
            column.addWidget(caption)
            column.addWidget(value)
            totals_layout.addLayout(column, 1)
            self.total_values[key] = value
        self.totals_widget.hide()
        self.scroll.setWidget(self.list_widget)
        content = QHBoxLayout()
        content.setSpacing(16)
        self.category_tree = QTreeWidget()
        self.category_tree.setHeaderHidden(True)
        self.category_tree.setFixedWidth(211)
        self.category_tree.setIndentation(14)
        self.category_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.category_tree.setAccessibleName("仓库分类")
        self.category_tree.itemSelectionChanged.connect(self.category_changed)
        self.category_tree.hide()
        content.addWidget(self.category_tree)
        content.addWidget(self.scroll, 1)
        outer.insertWidget(5, self.totals_widget)
        outer.addLayout(content, 1)
        outer.addSpacing(12)
        footer = QHBoxLayout()
        self.footer = label("上次记录 · 联网后更新", "footer")
        self.footer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        footer.addWidget(self.footer, 1)
        self.refresh_button = QPushButton("↻ 更新")
        self.refresh_button.setFixedSize(74, 29)
        self.refresh_button.setToolTip("立即更新 GitHub 状态 · F5 / Ctrl+R")
        self.refresh_button.setAccessibleName("刷新 GitHub 状态")
        self.refresh_button.clicked.connect(self.refresh)
        footer.addWidget(self.refresh_button)
        outer.addLayout(footer)

    def _build_controls(self, outer):
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(label("类型", "metricCaption"))
        self.type_filter = QComboBox()
        self.type_filter.setAccessibleName("类型筛选")
        self.type_filter.addItem("全部类型", None)
        for category in CATEGORY_TREE:
            self.type_filter.addItem(category, category)
        self.type_filter.setMinimumWidth(105)
        controls.addWidget(self.type_filter)
        controls.addWidget(label("最低 star", "metricCaption"))
        self.star_filter = QComboBox()
        self.star_filter.setAccessibleName("最低 star 筛选")
        for text, value in [("全部", None), ("≥ 3k", 3_000), ("≥ 7k", 7_000), ("≥ 10k", 10_000), ("≥ 50k", 50_000)]:
            self.star_filter.addItem(text, value)
        self.star_filter.setMinimumWidth(88)
        controls.addWidget(self.star_filter)
        controls.addWidget(label("排序", "metricCaption"))
        self.sort_filter = QComboBox()
        self.sort_filter.setAccessibleName("列表排序")
        for text, value in [("默认", "default"), ("等待时间长 → 短", "wait_desc"),
                            ("star 高 → 低", "stars_desc"), ("最近活动", "recent_desc"),
                            ("贡献行数多 → 少", "lines_desc")]:
            self.sort_filter.addItem(text, value)
        self.sort_filter.setMinimumWidth(150)
        controls.addWidget(self.sort_filter)
        controls.addStretch(1)
        self.add_candidate_button = QPushButton("＋ 添加仓库链接")
        self.add_candidate_button.setToolTip("输入 GitHub 仓库链接，加入候选池")
        self.add_candidate_button.clicked.connect(self.add_candidate)
        controls.addWidget(self.add_candidate_button)
        for control in (self.type_filter, self.star_filter, self.sort_filter):
            control.currentIndexChanged.connect(self.render)
        outer.addLayout(controls)

    def set_filter(self, phase: str):
        if phase != self.active_filter and {phase, self.active_filter} & {"repositories", "candidates"}:
            self.category_filter = (None, None)
        self.active_filter = phase
        self.render()

    def add_candidate(self):
        value, accepted = QInputDialog.getText(self, "加入候选仓库", "GitHub 仓库链接或 owner/name：")
        if not accepted:
            return
        repository = normalize_repository(value)
        if not repository:
            self.footer.setText("候选仓库链接格式不正确")
            return
        rows = self.snapshot.setdefault("candidate_repositories", [])
        known = {normalize_repository(row.get("repository") if isinstance(row, dict) else row) for row in rows}
        if repository not in known:
            rows.append({"repository": repository, "added_at": utc_now(), "source": "user"})
        self.snapshot.setdefault("candidates", {}).setdefault(repository, {"repository": repository})
        try:
            save_snapshot(self.snapshot, cache_path())
        except OSError:
            pass
        self.active_filter = "candidates"
        self.render()
        self.footer.setText(f"已加入候选池 · {repository} · 正在获取 Issue")
        if not self.offline:
            self.last_attempt = 0
            self.refresh()

    def category_changed(self):
        selected = self.category_tree.selectedItems()
        if selected:
            self.category_filter = tuple(selected[0].data(0, Qt.ItemDataRole.UserRole))
            self.render()

    def render_categories(self, repositories: list[str], metadata: dict, rules: dict):
        blocker = QSignalBlocker(self.category_tree)
        self.category_tree.clear()
        self.category_items = {}
        self.repository_categories = {name: classify_repository(name, metadata.get(name, {}), rules)
                                      for name in repositories}
        def add_item(parent, text, key):
            item = QTreeWidgetItem(parent, [text])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self.category_items[key] = item
            return item
        add_item(self.category_tree, f"全部仓库   {len(repositories)}", (None, None))
        for category, subcategories in CATEGORY_TREE.items():
            count = sum(c == category for c, _ in self.repository_categories.values())
            parent = add_item(self.category_tree, f"{category}   {count}", (category, None))
            for subcategory in subcategories:
                count = sum(pair == (category, subcategory) for pair in self.repository_categories.values())
                add_item(parent, f"{subcategory}   {count}", (category, subcategory))
        self.category_tree.expandAll()
        self.category_tree.setCurrentItem(self.category_items.get(self.category_filter, self.category_items[(None, None)]))
        del blocker

    def render(self):
        snapshot = self.snapshot or {}
        rules = load_rules()
        items = monitored_items(snapshot.get("items", []), rules)
        self.items = items
        repositories = contributed_repositories(items)
        candidates = candidate_repositories(snapshot)
        totals = snapshot.get("contribution_totals") or contribution_totals(
            items, snapshot.get("repositories", {}), None, None)
        totals.update(repositories=len(repositories))
        for key in self.total_values:
            value = totals.get(key)
            known = isinstance(value, int)
            if key == "lines":
                known = isinstance(totals.get("additions"), int) and isinstance(totals.get("deletions"), int) and totals.get("lines_ok", False)
                text = (f"+{totals['additions']:,} / −{totals['deletions']:,}" if known
                        else "待更新")
                self.total_values[key].setText(text)
                continue
            if key == "commits":
                known = known and totals.get("commits_ok", False)
            elif key == "stars":
                known = known and totals.get("stars_ok", False)
            elif key == "issues":
                known = known and totals.get("issues_ok", False)
            elif key == "downloads":
                known = known and totals.get("downloads_ok", False)
            text = f"{value:,}" if known else (f"{value:,} · 旧" if isinstance(value, int) else "待更新")
            self.total_values[key].setText(text)
        self.totals_widget.setVisible(self.active_filter == "repositories")
        self.category_tree.setVisible(self.active_filter in {"repositories", "candidates"})
        category_repositories = candidates if self.active_filter == "candidates" else repositories
        category_metadata = snapshot.get("candidates", {}) if self.active_filter == "candidates" else snapshot.get("repositories", {})
        self.render_categories(category_repositories, category_metadata, rules)
        for phase, button in self.tabs.items():
            count = (len(repositories) if phase == "repositories" else len(candidates) if phase == "candidates"
                     else sum(section(item) == phase for item in items))
            button.setText(f"{VIEWS[phase]}   {count}")
            button.setChecked(self.active_filter == phase)
        visible = [i for i in items if section(i) == self.active_filter]
        visible = self._filter_and_sort_items(visible, snapshot)
        while self.rows_layout.count():
            child = self.rows_layout.takeAt(0).widget()
            if child:
                child.hide()
                child.deleteLater()
        self.rows = []
        if self.active_filter == "repositories":
            repositories = self._filter_and_sort_repositories(repositories, items, snapshot)
            for repository in repositories:
                category, subcategory = self.repository_categories[repository]
                if self.category_filter[0] and self.category_filter[0] != category:
                    continue
                if self.category_filter[1] and self.category_filter[1] != subcategory:
                    continue
                card = RepositoryCard(repository, items, snapshot.get("repositories", {}).get(repository, {}))
                self.rows.append(card)
                self.rows_layout.addWidget(card)
        elif self.active_filter == "candidates":
            candidates = self._filter_and_sort_repositories(candidates, items, snapshot)
            for repository in candidates:
                category, subcategory = self.repository_categories[repository]
                if self.category_filter[0] and self.category_filter[0] != category:
                    continue
                if self.category_filter[1] and self.category_filter[1] != subcategory:
                    continue
                card = CandidateCard(repository, snapshot.get("candidates", {}).get(repository, {}),
                                     self.repository_categories.get(repository))
                self.rows.append(card)
                self.rows_layout.addWidget(card)
        else:
            self.totals_widget.hide()
            for item in visible:
                card = PullRequestCard(item, items, snapshot.get("repositories", {}).get(item["repository"], {}))
                self.rows.append(card)
                self.rows_layout.addWidget(card)
        if not self.rows:
            empty = QWidget()
            layout = QVBoxLayout(empty)
            layout.setContentsMargins(0, 95, 0, 40)
            title = label({"waiting": "暂时没有等待合并的 PR", "action": "暂无待处理事项", "merged": "还没有合并记录", "repositories": "还没有已合并贡献的仓库" if not repositories else "此分类下暂无已贡献仓库", "candidates": "候选池暂无仓库"}[self.active_filter], "emptyTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title)
            hint = label("你的 PR 合并后会自动归类收录" if self.active_filter == "repositories" else ("合并后会自动出现在这里" if self.active_filter == "merged" else ("点击右上角添加仓库链接" if self.active_filter == "candidates" else "最新进展会自动更新")), "emptyHint")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(hint)
            self.rows_layout.addWidget(empty)
        self.scroll.verticalScrollBar().setValue(0)

    def _repository_info(self, repository: str, snapshot: dict) -> dict:
        if self.active_filter == "candidates":
            return snapshot.get("candidates", {}).get(repository, {})
        return snapshot.get("repositories", {}).get(repository, {})

    def _matches_filters(self, repository: str, snapshot: dict) -> bool:
        info = self._repository_info(repository, snapshot)
        category, _ = self.repository_categories.get(repository, classify_repository(repository, info, load_rules()))
        selected_category = self.type_filter.currentData()
        if selected_category and category != selected_category:
            return False
        minimum_stars = self.star_filter.currentData()
        stars = info.get("stars")
        return minimum_stars is None or (isinstance(stars, int) and stars >= minimum_stars)

    def _filter_and_sort_items(self, items: list[dict], snapshot: dict) -> list[dict]:
        filtered = [item for item in items if self._matches_filters(item["repository"], snapshot)]
        mode = self.sort_filter.currentData()
        now = datetime.now(timezone.utc)
        if mode == "wait_desc":
            return sorted(filtered, key=lambda item: (wait_duration_seconds(item, now=now) is not None,
                                                      wait_duration_seconds(item, now=now) or -1), reverse=True)
        if mode == "stars_desc":
            return sorted(filtered, key=lambda item: (self._repository_info(item["repository"], snapshot).get("stars") or -1), reverse=True)
        if mode == "recent_desc":
            return sorted(filtered, key=lambda item: item.get("updated_at") or item.get("merged_at") or item.get("created_at") or "", reverse=True)
        if mode == "lines_desc":
            return sorted(filtered, key=lambda item: (item.get("additions") or 0) + (item.get("deletions") or 0), reverse=True)
        return filtered

    def _filter_and_sort_repositories(self, repositories: list[str], items: list[dict], snapshot: dict) -> list[str]:
        filtered = [repo for repo in repositories if self._matches_filters(repo, snapshot)]
        mode = self.sort_filter.currentData()
        if mode == "stars_desc":
            return sorted(filtered, key=lambda repo: self._repository_info(repo, snapshot).get("stars") or -1, reverse=True)
        merged_by_repo = {}
        for item in items:
            if item["repository"] in filtered and section(item) == "merged":
                merged_by_repo.setdefault(item["repository"], []).append(item)
        if mode == "wait_desc":
            now = datetime.now(timezone.utc)
            return sorted(filtered, key=lambda repo: max((wait_duration_seconds(item, now=now) or -1 for item in merged_by_repo.get(repo, [])), default=-1), reverse=True)
        if mode == "lines_desc":
            return sorted(filtered, key=lambda repo: sum((item.get("additions") or 0) + (item.get("deletions") or 0) for item in merged_by_repo.get(repo, [])), reverse=True)
        if mode == "recent_desc":
            return sorted(filtered, key=lambda repo: max((item.get("merged_at") or item.get("created_at") or "" for item in merged_by_repo.get(repo, [])), default=""), reverse=True)
        return filtered

    def refresh(self):
        if self.offline or (self.worker and self.worker.isRunning()):
            return
        # Mouse activation and manual refresh should not launch duplicate requests.
        if time.monotonic() - self.last_attempt < 3:
            return
        self.last_attempt = time.monotonic()
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("…")
        previous = date_text((self.snapshot or {}).get("updated_at"))
        self.footer.setText(f"同步中 · 上次记录 {previous}" if previous else "正在连接 GitHub…")
        self.worker = SyncWorker(self.snapshot, self)
        self.worker.received.connect(self.accept_snapshot)
        self.worker.failed.connect(self.sync_failed)
        self.worker.finished.connect(self.sync_finished)
        self.worker.start()

    def accept_snapshot(self, snapshot: dict, authenticated: bool):
        self.snapshot = snapshot
        self.authenticated = authenticated
        self.live = True
        try:
            save_snapshot(snapshot, cache_path())
        except OSError:
            pass
        self.render()
        now = datetime.now().strftime("%H:%M:%S")
        self.footer.setText(f"{'部分同步' if snapshot.get('partial') else '已同步'} · {now}")
        self.footer.setText(self.footer.text() + (" · 每分钟更新" if authenticated else " · 公开访问"))
        # Authenticated polling stays well within GitHub's usual 5,000/h limit.
        # Public access has a 60/h limit, so use an hourly automatic fallback.
        self.timer.start(60_000 if authenticated else 3_600_000)

    def sync_failed(self, message: str):
        self.live = False
        stamp = date_text((self.snapshot or {}).get("updated_at"))
        self.footer.setText(f"上次记录 {stamp} · {message}")
        self.timer.start(60_000)

    def sync_finished(self):
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("↻ 更新")
        if self._close_when_finished:
            self.close()

    _close_when_finished = False

    def closeEvent(self, event):
        self.timer.stop()
        if self.worker and self.worker.isRunning():
            # Hide immediately; let the bounded network operation finish so a
            # QThread is never destroyed while it is still running.
            self._close_when_finished = True
            self.worker.requestInterruption()
            self.hide()
            event.ignore()
        else:
            event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32":
            try:
                dark = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(dark), 4)
            except (AttributeError, OSError):
                pass


def create_application() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("贡献记录")
    app.setOrganizationName("MergeMonitor")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    palette = QPalette()
    for role, color in [(QPalette.ColorRole.Window, "#090909"), (QPalette.ColorRole.WindowText, "#ededed"),
                        (QPalette.ColorRole.Base, "#0e0e0e"), (QPalette.ColorRole.Text, "#ededed"),
                        (QPalette.ColorRole.Button, "#181818"), (QPalette.ColorRole.ButtonText, "#ededed"),
                        (QPalette.ColorRole.Highlight, "#454545"), (QPalette.ColorRole.HighlightedText, "#ffffff")]:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setWindowIcon(QIcon(str(ASSETS / "merge.ico")))
    return app
