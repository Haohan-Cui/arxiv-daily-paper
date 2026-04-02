from __future__ import annotations

import os
import queue
import threading
from datetime import date, timedelta
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, StringVar, Tk, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Dict

from tkcalendar import DateEntry

from app import (
    STAGE_SEQUENCE,
    build_runtime_institution_maps,
    institutions_text_from_terms,
    parse_institutions_text,
    run_pipeline,
)
from runtime_control import PipelineCancelled, PipelineController
from utils import now_local

UI_FONT = ("Microsoft YaHei UI", 10)
UI_FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
TITLE_FONT = ("Microsoft YaHei UI", 20, "bold")


def default_target_date() -> date:
    return now_local().date() - timedelta(days=1)


def build_result_overview(result: Dict[str, Any]) -> str:
    lines = [f"\u62a5\u544a\u65e5\u671f: {result.get('report_date') or '-'}"]
    filtered = result.get("filtered_candidates") or []
    cached = result.get("cached") or {}
    lines.append(f"\u901a\u8fc7\u7b5b\u9009\u8bba\u6587\u6570: {len(filtered)}")
    lines.append(f"\u7f13\u5b58 PDF \u6570: {len(cached)}")

    json_outputs = result.get("json_outputs") or {}
    if json_outputs:
        lines.append("")
        lines.append("\u8f93\u51fa\u6587\u4ef6:")
        for label, path in json_outputs.items():
            lines.append(f"- {label}: {path}")

    report = result.get("report")
    if report is not None:
        lines.append("")
        lines.append("\u9636\u6bb5\u62a5\u544a:")
        lines.extend(report.summary_lines())

    if filtered:
        lines.append("")
        lines.append("\u8bba\u6587\u5217\u8868:")
        for entry in filtered[:100]:
            title = entry.get("title") or "(\u65e0\u6807\u9898)"
            category = entry.get("primary_category") or "-"
            published = entry.get("published")
            published_text = published.strftime("%Y-%m-%d %H:%M") if published else "-"
            lines.append(f"- [{category}] {title} ({published_text})")
        remaining = len(filtered) - 100
        if remaining > 0:
            lines.append(f"- \u5176\u4f59 {remaining} \u7bc7\u8bf7\u67e5\u770b manifest JSON")
    return "\n".join(lines)


class DailyPaperDesktop:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("DailyPaper \u8bba\u6587\u6293\u53d6\u5668")
        self.root.geometry("1280x860")
        self.root.minsize(1120, 760)

        self.status_var = StringVar(value="\u5c31\u7eea")
        self.stage_var = StringVar(value="\u5f53\u524d\u9636\u6bb5: \u672a\u5f00\u59cb")
        self.progress_var = StringVar(value="0%")
        self.selected_date_var = StringVar(value=default_target_date().isoformat())
        self.current_result: Dict[str, Any] | None = None
        self.controller: PipelineController | None = None
        self.event_queue: queue.Queue[tuple[str, int, Any]] = queue.Queue()
        self.running = False
        self.active_task_id = 0

        self._build_ui()
        self.root.after(120, self._drain_events)

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=BOTH, expand=True)

        header = ttk.Frame(container)
        header.pack(fill=X, pady=(0, 12))
        ttk.Label(header, text="DailyPaper \u8bba\u6587\u6293\u53d6\u5668", font=TITLE_FONT).pack(anchor="w")
        ttk.Label(
            header,
            text="\u9009\u62e9 arXiv \u670d\u52a1\u5668\u65e5\u671f\uff0c\u7f16\u8f91\u673a\u6784\u5217\u8868\uff0c\u5728\u684c\u9762\u7a97\u53e3\u5185\u76f4\u63a5\u6293\u53d6\u3001\u7f13\u5b58\u5e76\u67e5\u770b\u62a5\u544a\u3002",
            font=UI_FONT,
        ).pack(anchor="w", pady=(6, 0))

        body = ttk.Panedwindow(container, orient="horizontal")
        body.pack(fill=BOTH, expand=True)

        left = ttk.Frame(body, padding=(0, 0, 12, 0))
        right = ttk.Frame(body)
        body.add(left, weight=2)
        body.add(right, weight=3)

        control_card = ttk.LabelFrame(left, text="\u8fd0\u884c\u53c2\u6570", padding=12)
        control_card.pack(fill=BOTH, expand=True)

        date_row = ttk.Frame(control_card)
        date_row.pack(fill=X, pady=(0, 10))
        ttk.Label(date_row, text="\u76ee\u6807\u65e5\u671f:", font=UI_FONT).pack(side=LEFT)
        self.date_picker = DateEntry(
            date_row,
            width=16,
            locale="zh_CN",
            date_pattern="yyyy-mm-dd",
            firstweekday="monday",
            font=UI_FONT,
        )
        self.date_picker.pack(side=LEFT, padx=(10, 8))
        self.date_picker.set_date(default_target_date())
        self.date_picker.bind("<<DateEntrySelected>>", self._sync_date_label)
        ttk.Button(date_row, text="\u8bbe\u4e3a\u6628\u5929", command=self._set_yesterday).pack(side=LEFT)
        ttk.Label(date_row, textvariable=self.selected_date_var, font=UI_FONT_BOLD).pack(side=LEFT, padx=(12, 0))

        ttk.Label(control_card, text="\u673a\u6784\u5217\u8868\u6bcf\u884c\u4e00\u6761\u3002\u683c\u5f0f: \u673a\u6784\u540d: \u522b\u540d1, \u522b\u540d2", font=UI_FONT).pack(anchor="w")

        self.institutions_text = ScrolledText(control_card, wrap="word", height=24, font=UI_FONT)
        self.institutions_text.pack(fill=BOTH, expand=True, pady=(8, 12))
        self.institutions_text.insert("1.0", institutions_text_from_terms())

        button_row = ttk.Frame(control_card)
        button_row.pack(fill=X)
        self.run_button = ttk.Button(button_row, text="\u5f00\u59cb\u6293\u53d6", command=self._run_pipeline_async)
        self.run_button.pack(side=LEFT)
        self.pause_button = ttk.Button(button_row, text="\u6682\u505c", command=self._pause_pipeline, state="disabled")
        self.pause_button.pack(side=LEFT, padx=(8, 0))
        self.resume_button = ttk.Button(button_row, text="\u7ee7\u7eed", command=self._resume_pipeline, state="disabled")
        self.resume_button.pack(side=LEFT, padx=(8, 0))
        self.cancel_button = ttk.Button(button_row, text="\u53d6\u6d88\u5168\u90e8", command=self._cancel_pipeline, state="disabled")
        self.cancel_button.pack(side=LEFT, padx=(8, 0))

        more_button_row = ttk.Frame(control_card)
        more_button_row.pack(fill=X, pady=(8, 0))
        ttk.Button(more_button_row, text="\u8ffd\u52a0\u673a\u6784\u6a21\u677f", command=self._append_institution_row).pack(side=LEFT)
        ttk.Button(more_button_row, text="\u6062\u590d\u9ed8\u8ba4\u673a\u6784", command=self._reset_institutions).pack(side=LEFT, padx=(8, 0))

        result_card = ttk.LabelFrame(right, text="\u8fd0\u884c\u7ed3\u679c", padding=12)
        result_card.pack(fill=BOTH, expand=True)

        progress_row = ttk.Frame(result_card)
        progress_row.pack(fill=X, pady=(0, 8))
        ttk.Label(progress_row, textvariable=self.status_var, font=UI_FONT).pack(side=LEFT)
        ttk.Label(progress_row, textvariable=self.progress_var, font=UI_FONT_BOLD).pack(side=RIGHT)

        ttk.Label(result_card, textvariable=self.stage_var, font=UI_FONT).pack(anchor="w")
        self.progress = ttk.Progressbar(result_card, mode="determinate", maximum=100)
        self.progress.pack(fill=X, pady=(6, 10))

        status_row = ttk.Frame(result_card)
        status_row.pack(fill=X, pady=(0, 8))
        ttk.Button(status_row, text="\u6253\u5f00\u62a5\u544a\u76ee\u5f55", command=self._open_report_dir).pack(side=RIGHT)
        ttk.Button(status_row, text="\u6253\u5f00\u7f13\u5b58\u76ee\u5f55", command=self._open_cache_dir).pack(side=RIGHT, padx=(0, 8))

        notebook = ttk.Notebook(result_card)
        notebook.pack(fill=BOTH, expand=True)

        log_tab = ttk.Frame(notebook)
        summary_tab = ttk.Frame(notebook)
        notebook.add(log_tab, text="\u5b9e\u65f6\u65e5\u5fd7")
        notebook.add(summary_tab, text="\u7ed3\u679c\u6458\u8981")

        self.log_text = ScrolledText(log_tab, wrap="word", font=UI_FONT)
        self.log_text.pack(fill=BOTH, expand=True)
        self.log_text.insert("1.0", "\u8fd0\u884c\u540e\uff0c\u8fd9\u91cc\u4f1a\u6301\u7eed\u663e\u793a\u4e2d\u95f4\u8fdb\u5ea6\u3001\u9636\u6bb5\u5207\u6362\u548c\u544a\u8b66\u4fe1\u606f\u3002")
        self.log_text.configure(state="disabled")

        self.output_text = ScrolledText(summary_tab, wrap="word", font=UI_FONT)
        self.output_text.pack(fill=BOTH, expand=True)
        self.output_text.insert("1.0", "\u8fd0\u884c\u5b8c\u6210\u540e\uff0c\u8fd9\u91cc\u4f1a\u663e\u793a\u62a5\u544a\u6458\u8981\u548c\u8bba\u6587\u5217\u8868\u3002")
        self.output_text.configure(state="disabled")

    def _sync_date_label(self, _event=None) -> None:
        try:
            self.selected_date_var.set(self.date_picker.get_date().isoformat())
        except Exception:
            pass

    def _set_yesterday(self) -> None:
        target = default_target_date()
        self.date_picker.set_date(target)
        self.selected_date_var.set(target.isoformat())
        self.root.update_idletasks()

    def _append_institution_row(self) -> None:
        current = self.institutions_text.get("1.0", END).rstrip()
        suffix = "\n" if current else ""
        self.institutions_text.delete("1.0", END)
        self.institutions_text.insert("1.0", current + suffix + "\u65b0\u673a\u6784: \u522b\u540d1, \u522b\u540d2")

    def _reset_institutions(self) -> None:
        self.institutions_text.delete("1.0", END)
        self.institutions_text.insert("1.0", institutions_text_from_terms())

    def _set_summary(self, text: str) -> None:
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", END)
        self.output_text.insert("1.0", text)
        self.output_text.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(END, text + "\n")
        self.log_text.see(END)
        self.log_text.configure(state="disabled")

    def _set_running_state(self, running: bool) -> None:
        self.running = running
        self.run_button.configure(state="disabled" if running else "normal")
        self.pause_button.configure(state="normal" if running else "disabled")
        self.resume_button.configure(state="disabled")
        self.cancel_button.configure(state="normal" if running else "disabled")
        if not running:
            self.controller = None

    def _run_pipeline_async(self) -> None:
        try:
            target_day = self.date_picker.get_date()
            self.selected_date_var.set(target_day.isoformat())
            custom_entries = parse_institutions_text(self.institutions_text.get("1.0", END))
            org_search_terms, institution_patterns = build_runtime_institution_maps(custom_entries)
        except Exception as exc:
            messagebox.showerror("\u8f93\u5165\u9519\u8bef", f"\u53c2\u6570\u89e3\u6790\u5931\u8d25: {exc}")
            return

        self.active_task_id += 1
        task_id = self.active_task_id
        self.controller = PipelineController()
        self._set_running_state(True)
        self.current_result = None
        self.status_var.set("\u6b63\u5728\u8fd0\u884c")
        self.stage_var.set("\u5f53\u524d\u9636\u6bb5: \u51c6\u5907\u4e2d")
        self.progress["value"] = 0
        self.progress_var.set("0%")
        self._append_log(f"\u65b0\u4efb\u52a1\u5df2\u542f\u52a8\uff0c\u76ee\u6807\u65e5\u671f: {target_day.isoformat()}")
        self._set_summary("\u6b63\u5728\u6267\u884c\u6293\u53d6\u4efb\u52a1\uff0c\u8bf7\u7a0d\u5019...\n\u4f60\u53ef\u4ee5\u5728\u9636\u6bb5\u4e4b\u95f4\u6682\u505c\u6216\u53d6\u6d88\u3002")

        worker = threading.Thread(
            target=self._run_pipeline_worker,
            args=(task_id, target_day, org_search_terms, institution_patterns),
            daemon=True,
        )
        worker.start()

    def _run_pipeline_worker(self, task_id: int, target_day, org_search_terms, institution_patterns) -> None:
        controller = self.controller
        assert controller is not None

        def callback(stage: str, message: str, state: str = "info", percent: float | None = None) -> None:
            self.event_queue.put(("progress", task_id, {"stage": stage, "message": message, "state": state, "percent": percent}))

        try:
            result = run_pipeline(
                target_day=target_day,
                org_search_terms=org_search_terms,
                institution_patterns=institution_patterns,
                controller=controller,
                progress_callback=callback,
            )
            self.event_queue.put(("success", task_id, result))
        except PipelineCancelled:
            self.event_queue.put(("cancelled", task_id, None))
        except Exception as exc:
            self.event_queue.put(("error", task_id, exc))

    def _pause_pipeline(self) -> None:
        if not self.controller or self.controller.paused:
            return
        self.controller.pause()
        self.status_var.set("\u5df2\u8bf7\u6c42\u6682\u505c")
        self.pause_button.configure(state="disabled")
        self.resume_button.configure(state="normal")
        self._append_log("\u5df2\u8bf7\u6c42\u6682\u505c\uff0c\u5c06\u5728\u4e0b\u4e00\u4e2a\u5b89\u5168\u68c0\u67e5\u70b9\u751f\u6548\u3002")

    def _resume_pipeline(self) -> None:
        if not self.controller or not self.controller.paused:
            return
        self.controller.resume()
        self.status_var.set("\u5df2\u7ee7\u7eed\u8fd0\u884c")
        self.pause_button.configure(state="normal")
        self.resume_button.configure(state="disabled")
        self._append_log("\u5df2\u7ee7\u7eed\u8fd0\u884c\u3002")

    def _cancel_pipeline(self) -> None:
        if not self.controller:
            return
        self.controller.cancel()
        cancelled_task_id = self.active_task_id
        self.active_task_id += 1
        self._set_running_state(False)
        self.status_var.set("\u5df2\u53d6\u6d88")
        self.stage_var.set("\u5f53\u524d\u9636\u6bb5: \u5df2\u53d6\u6d88")
        self._append_log("\u5df2\u8bf7\u6c42\u53d6\u6d88\u5168\u90e8\u4efb\u52a1\u3002")
        self._set_summary("\u4efb\u52a1\u5df2\u53d6\u6d88\u3002\n\u5df2\u5b8c\u6210\u7684\u7f13\u5b58\u548c\u62a5\u544a\u4f1a\u4fdd\u7559\u3002")
        self.event_queue.put(("cancelled", cancelled_task_id, None))

    def _global_progress(self, stage: str, percent: float | None) -> float:
        if stage not in STAGE_SEQUENCE:
            return float(self.progress["value"])
        idx = STAGE_SEQUENCE.index(stage)
        start = (idx / len(STAGE_SEQUENCE)) * 100.0
        end = ((idx + 1) / len(STAGE_SEQUENCE)) * 100.0
        if percent is None:
            return max(float(self.progress["value"]), start)
        local = max(0.0, min(percent, 100.0)) / 100.0
        return start + (end - start) * local

    def _drain_events(self) -> None:
        try:
            while True:
                kind, task_id, payload = self.event_queue.get_nowait()
                if task_id != self.active_task_id and kind != "cancelled":
                    continue
                if kind == "progress":
                    self._handle_progress(payload)
                elif kind == "success":
                    self._handle_success(payload)
                elif kind == "cancelled":
                    self._handle_cancelled()
                elif kind == "error":
                    self._handle_error(payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._drain_events)

    def _handle_progress(self, payload: Dict[str, Any]) -> None:
        stage = payload["stage"]
        message = payload["message"]
        state = payload.get("state") or "info"
        percent = payload.get("percent")
        global_percent = self._global_progress(stage, percent)
        self.progress["value"] = global_percent
        self.progress_var.set(f"{global_percent:.0f}%")
        self.stage_var.set(f"\u5f53\u524d\u9636\u6bb5: {stage}")
        if state == "warning":
            self.status_var.set("\u8fd0\u884c\u4e2d\uff0c\u6709\u8b66\u544a")
        elif state == "cancelled":
            self.status_var.set("\u5df2\u53d6\u6d88")
        elif state == "error":
            self.status_var.set("\u8fd0\u884c\u5931\u8d25")
        elif state == "ok":
            self.status_var.set("\u9636\u6bb5\u5b8c\u6210")
        else:
            if self.controller and self.controller.paused:
                self.status_var.set("\u5df2\u6682\u505c")
            else:
                self.status_var.set("\u8fd0\u884c\u4e2d")
        self._append_log(f"[{stage}][{state}] {message}")

    def _handle_success(self, result: Dict[str, Any]) -> None:
        self.current_result = result
        self._set_running_state(False)
        self.status_var.set("\u6293\u53d6\u5b8c\u6210")
        self.stage_var.set("\u5f53\u524d\u9636\u6bb5: \u5168\u90e8\u5b8c\u6210")
        self.progress["value"] = 100
        self.progress_var.set("100%")
        self._set_summary(build_result_overview(result))
        self._append_log("\u5168\u90e8\u4efb\u52a1\u5df2\u5b8c\u6210\u3002")

    def _handle_cancelled(self) -> None:
        self._set_running_state(False)
        self.status_var.set("\u5df2\u53d6\u6d88")
        self.stage_var.set("\u5f53\u524d\u9636\u6bb5: \u5df2\u53d6\u6d88")
        self._append_log("\u4efb\u52a1\u5df2\u53d6\u6d88\u3002")

    def _handle_error(self, exc: Exception) -> None:
        self._set_running_state(False)
        self.status_var.set("\u6267\u884c\u5931\u8d25")
        self.stage_var.set("\u5f53\u524d\u9636\u6bb5: \u5931\u8d25")
        self._set_summary(f"\u6267\u884c\u5931\u8d25:\n{exc}")
        self._append_log(f"[error] {exc}")
        messagebox.showerror("\u6267\u884c\u5931\u8d25", str(exc))

    def _open_report_dir(self) -> None:
        if not self.current_result:
            messagebox.showinfo("\u63d0\u793a", "\u8bf7\u5148\u8fd0\u884c\u4e00\u6b21\u6293\u53d6\u4efb\u52a1\u3002")
            return
        self._open_parent_of_output("report")

    def _open_cache_dir(self) -> None:
        if not self.current_result:
            messagebox.showinfo("\u63d0\u793a", "\u8bf7\u5148\u8fd0\u884c\u4e00\u6b21\u6293\u53d6\u4efb\u52a1\u3002")
            return
        report_date = self.current_result.get("report_date")
        if not report_date:
            messagebox.showinfo("\u63d0\u793a", "\u5f53\u524d\u7ed3\u679c\u6ca1\u6709\u62a5\u544a\u65e5\u671f\u3002")
            return
        self._open_path(Path("cache_pdfs") / report_date)

    def _open_parent_of_output(self, key: str) -> None:
        outputs = (self.current_result or {}).get("json_outputs") or {}
        path = outputs.get(key)
        if not path:
            messagebox.showinfo("\u63d0\u793a", "\u5f53\u524d\u6ca1\u6709\u53ef\u6253\u5f00\u7684\u8f93\u51fa\u76ee\u5f55\u3002")
            return
        self._open_path(Path(path).parent)

    def _open_path(self, path: Path) -> None:
        try:
            os.startfile(path.resolve())
        except Exception as exc:
            messagebox.showerror("\u6253\u5f00\u5931\u8d25", f"\u65e0\u6cd5\u6253\u5f00\u76ee\u5f55: {exc}")


def main() -> None:
    root = Tk()
    DailyPaperDesktop(root)
    root.mainloop()


if __name__ == "__main__":
    main()
