"""카메라 선택 위젯.

노트북 내장캠과 USB 웹캠처럼 카메라가 둘 이상 잡히는 환경에서는 어떤 장치를
쓸지 앱이 대신 정할 수 없다. 이 위젯은 연결된 카메라를 조회해 두 대 이상일 때
사용자가 직접 고르게 하고, 한 대뿐이면 그 장치를 그대로 쓴다.

장치 조회는 카메라를 실제로 열어 보므로 수 초가 걸릴 수 있다. Tk 메인 스레드가
멈추지 않도록 조회는 워커 스레드에서 하고, 위젯 갱신은 ``after``로 메인
스레드에 돌려준다(Tk는 스레드 안전하지 않다).
"""
from __future__ import annotations

import threading
import tkinter as tk
import traceback
from tkinter import messagebox, ttk
from typing import Callable

from common.camera import CameraDevice, list_cameras, selectable_devices

BusyCallback = Callable[[], bool]


def scan_status(devices: tuple[CameraDevice, ...], detected: bool) -> str:
    """조회 결과를 사용자용 한 줄 상태 문구로 만든다."""
    if not detected:
        return "카메라를 찾지 못했습니다 · 번호를 직접 선택하세요"
    if len(devices) == 1:
        return "카메라 1대 · 자동 선택됨"
    return f"카메라 {len(devices)}대 감지 · 사용할 카메라를 선택하세요"


class CameraSelector(ttk.LabelFrame):
    """연결된 카메라를 조회해 하나를 고르게 하는 사이드바 위젯."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        busy: BusyCallback | None = None,
        auto_scan: bool = True,
    ) -> None:
        super().__init__(master, text="카메라 선택", padding=8)
        self.root = master.winfo_toplevel()
        self._busy = busy or (lambda: False)

        self._devices: tuple[CameraDevice, ...] = ()
        self._scan_thread: threading.Thread | None = None

        self.columnconfigure(0, weight=1)

        self.choice_var = tk.StringVar(value="검색 중...")
        self.combo = ttk.Combobox(
            self,
            textvariable=self.choice_var,
            values=[],
            state="disabled",
            width=24,
        )
        self.combo.grid(row=0, column=0, sticky="ew")

        self.refresh_button = ttk.Button(
            self, text="다시 검색", width=9, command=self.refresh
        )
        self.refresh_button.grid(row=0, column=1, sticky="e", padx=(6, 0))

        self.status_var = tk.StringVar(value="카메라 검색 중...")
        ttk.Label(
            self, textvariable=self.status_var, wraplength=390, anchor="w"
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        if auto_scan:
            self.refresh()

    # ------------------------------------------------------------------ 조회

    def refresh(self) -> None:
        """카메라 목록을 다시 조회한다. 조회 중이면 아무 일도 하지 않는다."""
        if self.is_scanning():
            return
        if self._busy():
            messagebox.showwarning(
                "카메라 사용 중",
                "실행 중인 웹캠·OMX 작업을 먼저 종료한 뒤 다시 검색하세요.",
                parent=self.root,
            )
            return
        self.refresh_button.configure(state="disabled")
        self.combo.configure(state="disabled")
        self.status_var.set("카메라 검색 중...")
        self._scan_thread = threading.Thread(
            target=self._scan_worker, daemon=True
        )
        self._scan_thread.start()

    def is_scanning(self) -> bool:
        return self._scan_thread is not None and self._scan_thread.is_alive()

    def _scan_worker(self) -> None:
        try:
            devices = list_cameras(refresh=True)
        except Exception:
            traceback.print_exc()
            devices = ()
        try:
            self.after(0, self._apply_devices, devices)
        except tk.TclError:
            # 조회 도중 창이 닫혔다면 갱신할 위젯도 없다.
            pass

    def _apply_devices(self, devices: tuple[CameraDevice, ...]) -> None:
        if not self.winfo_exists():
            return
        self._scan_thread = None
        detected = bool(devices)
        self._devices = selectable_devices(devices)
        labels = [device.label for device in self._devices]

        self.combo.configure(values=labels)
        self.choice_var.set(labels[0])
        # 고를 것이 하나뿐이면 선택 상자를 열어 봐야 할 일이 없다.
        self.combo.configure(
            state="readonly" if len(labels) > 1 else "disabled"
        )
        self.refresh_button.configure(state="normal")
        self.status_var.set(scan_status(self._devices, detected))
        print(
            "[camera] 사용 가능한 카메라: "
            + (", ".join(labels) if detected else "없음(기본 번호 표시)")
        )

    # ------------------------------------------------------------------ 선택값

    def selected_device(self) -> CameraDevice | None:
        if not self._devices:
            return None
        current = self.combo.current()
        if current < 0 or current >= len(self._devices):
            return self._devices[0]
        return self._devices[current]

    def selected_index(self) -> int:
        """선택한 카메라 번호. 아직 조회 전이면 0번을 쓴다."""
        device = self.selected_device()
        return 0 if device is None else device.index
