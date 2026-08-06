from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from grant_review.ai_review import list_ollama_models
from grant_review.local_backend import DEFAULT_GUIDE, LocalReviewService

APP_TITLE = "基金申请书本地整理与评审助手"
APP_VERSION = "0.1.0"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", ROOT))
    return base / relative


class DesktopAPI:
    def __init__(self) -> None:
        self.service = LocalReviewService()
        self.window: Any = None

    def set_window(self, window: Any) -> None:
        self.window = window

    def _safe(self, func: Callable[[], Any]) -> Any:
        try:
            return func()
        except Exception as exc:
            # The desktop build has no console. Return a concise local error to
            # the UI; the traceback is only available in debug builds.
            if os.getenv("GRANT_REVIEW_DEBUG") == "1":
                traceback.print_exc()
            return {"ok": False, "message": str(exc)}

    def ping(self) -> dict[str, Any]:
        return {
            "ok": True,
            "title": APP_TITLE,
            "version": APP_VERSION,
            "default_guide": DEFAULT_GUIDE,
            "platform": sys.platform,
            "default_output_dir": str((Path.home() / "Documents").resolve()),
        }

    def choose_pdf_files(self) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            import webview

            selected = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=("PDF 文件 (*.pdf)", "所有文件 (*.*)"),
            )
            paths = [str(path) for path in (selected or [])]
            return {"ok": True, "files": self.service.inspect_pdf_paths(paths)}

        return self._safe(action)

    def choose_output_folder(self) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            import webview

            selected = self.window.create_file_dialog(webview.FOLDER_DIALOG)
            value = ""
            if isinstance(selected, (list, tuple)) and selected:
                value = str(selected[0])
            elif isinstance(selected, str):
                value = selected
            return {"ok": True, "path": value}

        return self._safe(action)

    def choose_batch_file(self) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            import webview

            selected = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("基金评审批次 (*.json)", "JSON 文件 (*.json)"),
            )
            path = str(selected[0]) if selected else ""
            if not path:
                return {"ok": False, "message": "未选择文件。"}
            return self.service.load_batch(path)

        return self._safe(action)

    def process_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._safe(lambda: self.service.process_batch(payload))

    def get_batch_summary(self) -> dict[str, Any]:
        return self._safe(lambda: {"ok": True, "batch": self.service.batch_summary()})

    def get_record_detail(self, index: int) -> dict[str, Any]:
        return self._safe(lambda: {"ok": True, "detail": self.service.record_detail(int(index))})

    def update_record(self, index: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self._safe(lambda: self.service.update_record(int(index), payload))

    def generate_initial_reviews(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._safe(lambda: self.service.generate_initial_reviews(payload))

    def generate_final_reviews(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._safe(lambda: self.service.generate_final_reviews(payload))

    def export_batch(self) -> dict[str, Any]:
        return self._safe(self.service.export)

    def open_output_folder(self) -> dict[str, Any]:
        return self._safe(self.service.open_output_folder)

    def clear_batch(self) -> dict[str, Any]:
        return self._safe(self.service.clear)

    def detect_ollama_models(self, base_url: str = "http://127.0.0.1:11434") -> dict[str, Any]:
        return self._safe(lambda: {"ok": True, "models": list_ollama_models(base_url)})

    def close_app(self) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            if self.window is not None:
                self.window.destroy()
            return {"ok": True}

        return self._safe(action)


def main() -> None:
    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "缺少 pywebview。开发环境请运行 pip install -r requirements.txt；正式用户应使用打包后的应用。"
        ) from exc

    index_file = resource_path("ui/index.html")
    if not index_file.exists():
        raise SystemExit(f"找不到界面文件：{index_file}")

    api = DesktopAPI()
    window = webview.create_window(
        APP_TITLE,
        url=index_file.as_uri(),
        js_api=api,
        width=1360,
        height=880,
        min_size=(980, 680),
        resizable=True,
        text_select=True,
    )
    api.set_window(window)
    webview.start(debug=os.getenv("GRANT_REVIEW_DEBUG") == "1")


if __name__ == "__main__":
    main()
