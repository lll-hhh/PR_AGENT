"""Launch the contribution dashboard and its packaged smoke checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QTimer

from merge_monitor.state import SECTIONS, VIEWS, contributed_repositories, display_status, later_merge_summary, repository_summary, section, status_label
from merge_monitor.ui import MainWindow, create_application


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", type=Path, metavar="OUTPUT_DIR")
    parser.add_argument("--smoke-test", type=Path, metavar="OUTPUT_DIR")
    args = parser.parse_args()
    app = create_application()
    window = MainWindow(offline=bool(args.self_test))
    window.show()
    output = args.self_test or args.smoke_test
    result = {"ok": False}
    if output:
        output.mkdir(parents=True, exist_ok=True)
        captured = False

        def capture():
            nonlocal captured
            if captured:
                return
            captured = True
            snapshot = window.snapshot or {}
            items = window.items
            result.update(
                ok=bool(snapshot.get("items")) and (bool(args.self_test) or window.live),
                live=window.live,
                footer=window.footer.text(),
                counts={phase: sum(section(i) == phase for i in items) for phase in SECTIONS},
                items=[{"repository": i["repository"], "number": i["number"], "status": display_status(i),
                        "github_status": status_label(i),
                        "merge_order": later_merge_summary(i, snapshot.get("repositories", {}).get(i["repository"], {}))}
                       for i in items],
                repositories={name: dict(info, contributions=repository_summary(snapshot.get("items", []), name, merged_only=True))
                              for name, info in snapshot.get("repositories", {}).items()},
            )
            result["counts"]["repositories"] = len(contributed_repositories(items))
            result["repository_cards"] = {}
            result["view_details"] = {}
            for phase in VIEWS:
                window.tabs[phase].click()
                app.processEvents()
                result["repository_cards"][phase] = len(window.rows)
                result["view_details"][phase] = [
                    {"repository": row.repository, "number": getattr(row, "item", {}).get("number"),
                     "metrics": {caption: value.text() for caption, value in row.metrics.items()}}
                    for row in window.rows
                ]
                window.grab().save(str(output / f"{phase}.png"))
            result["categories"] = {str(key): item.text(0) for key, item in window.category_items.items()}
            (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            window.close()
            if window.worker and window.worker.isRunning():
                window.worker.finished.connect(app.quit)
            else:
                app.quit()

        if args.self_test:
            QTimer.singleShot(500, capture)
        else:
            poll = QTimer(window)

            def check():
                if window.worker and window.worker.isFinished():
                    poll.stop()
                    capture()

            poll.timeout.connect(check)
            poll.start(200)
            QTimer.singleShot(90_000, capture)
    app.exec()
    # Destroy widgets while QApplication and the GUI thread still exist.
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return 0 if not output or result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
