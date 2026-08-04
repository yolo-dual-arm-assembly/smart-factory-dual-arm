from __future__ import annotations

import queue
import sys
import tkinter as tk
from tkinter import ttk
from typing import TextIO

CONSOLE_BG = "#1e1e1e"
CONSOLE_FG = "#d4d4d4"
CONSOLE_CARET = "#ffffff"
CONSOLE_FONT = "TkFixedFont"
CONSOLE_MAX_LINES = 1_000
CONSOLE_TRIM_LINES = 200


class ConsoleStream:
    """Send standard output to the GUI without blocking worker threads."""

    def __init__(self, output_queue: queue.SimpleQueue[str], original: TextIO) -> None:
        self._output_queue = output_queue
        self._original = original

    def write(self, message: str) -> int:
        if message:
            self._output_queue.put(message)
            try:
                self._original.write(message)
            except Exception:
                pass
        return len(message)

    def flush(self) -> None:
        try:
            self._original.flush()
        except Exception:
            pass


class ConsoleRedirector:
    """Route sys.stdout/stderr into a queue while echoing to the originals."""

    def __init__(self) -> None:
        self.queue: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

    def install(self) -> None:
        sys.stdout = ConsoleStream(self.queue, self._original_stdout)
        sys.stderr = ConsoleStream(self.queue, self._original_stderr)

    def restore(self) -> None:
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr


class ConsolePanel(ttk.LabelFrame):
    """Read-only console widget fed from a message queue."""

    def __init__(
        self, master: tk.Misc, message_queue: queue.SimpleQueue[str]
    ) -> None:
        super().__init__(master, text="콘솔 출력", padding=(8, 6))
        self._queue = message_queue
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.text = tk.Text(
            self,
            height=9,
            wrap="word",
            state="disabled",
            background=CONSOLE_BG,
            foreground=CONSOLE_FG,
            insertbackground=CONSOLE_CARET,
            font=CONSOLE_FONT,
        )
        self.text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scrollbar.set)
        ttk.Button(self, text="지우기", command=self.clear).grid(
            row=1, column=0, columnspan=2, sticky="e", pady=(6, 0)
        )

    def drain(self) -> None:
        messages: list[str] = []
        while True:
            try:
                messages.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if messages:
            self.text.configure(state="normal")
            self.text.insert(tk.END, "".join(messages))
            if int(self.text.index("end-1c").split(".")[0]) > CONSOLE_MAX_LINES:
                self.text.delete("1.0", f"{CONSOLE_TRIM_LINES}.0")
            self.text.see(tk.END)
            self.text.configure(state="disabled")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.configure(state="disabled")
