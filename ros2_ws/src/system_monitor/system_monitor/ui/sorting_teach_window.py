"""OMX2(분류) 웨이포인트 교시 창.

``omx2_sorting/teach_motion.py``의 터미널 교시(r/t/ENTER/c/o/p/u/s)를 그대로
GUI로 옮긴 것이다. 흐름과 저장 형식이 같으므로 두 도구는 서로의 결과를
이어서 쓸 수 있다.

- **Torque OFF**: 손으로 팔을 원하는 자세로 움직인다.
- **Torque ON**: 자세를 고정한다. 이 상태에서만 저장할 수 있다 — OFF 상태로
  읽으면 손을 떼는 순간의 흔들리는 값이 저장되기 때문이다.
- 시퀀스는 ``move`` / ``gripper_close`` / ``gripper_open`` 스텝의 나열이고,
  저장 파일은 ``omx2_sorting/config/{pass,reject}_waypoints.json``이다
  (:mod:`omx2_sorting.pass_motion`이 재생하는 바로 그 파일).

.. warning::
   창을 닫으면 ``disconnect()``가 전 관절 토크를 끄므로 팔이 처질 수 있다.
   터미널 교시(teach_motion)도 같은 동작이다. 닫기 전에 확인을 받는다.
"""
from __future__ import annotations

import json
import math
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from common.omx_controller import OmxConfig, OmxController
from omx2_sorting.pass_motion import PASS_PATH
from omx2_sorting.reject_motion import REJECT_PATH

MOTION_PATHS: dict[str, Path] = {"PASS": PASS_PATH, "REJECT": REJECT_PATH}
DEFAULT_MOVE_DURATION = 2.0
DEFAULT_GRIPPER_DURATION = 1.0


def _step_label(index: int, step: dict) -> str:
    """Listbox 한 줄. teach_motion의 print_sequence와 같은 어휘를 쓴다."""
    action = step.get("action", "?")
    if action == "move":
        angles = step.get("angles", [])
        joints = " ".join(f"{math.degrees(a):6.1f}" for a in angles)
        return f"{index}. MOVE  [{joints}]"
    if action == "gripper_close":
        return f"{index}. GRIPPER CLOSE"
    if action == "gripper_open":
        return f"{index}. GRIPPER OPEN"
    return f"{index}. {action}"


class SortingTeachWindow(tk.Toplevel):
    """분류 팔의 PASS/REJECT 웨이포인트를 직접 교시로 만든다."""

    def __init__(
        self,
        master: tk.Misc,
        port: str,
        *,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.title("OMX 2 분류 동작 교시")
        self.geometry("560x520")
        self.minsize(480, 420)

        self.on_closed = on_closed
        self.controller = OmxController(OmxConfig(port=port))
        self._connected = False
        self._torque_on = False
        self._closing = False
        self.sequence: list[dict] = []

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # 연결은 몇 초 걸릴 수 있으므로 창을 먼저 띄우고 백그라운드로 붙는다.
        threading.Thread(target=self._connect_worker, daemon=True).start()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=8)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="동작").grid(row=0, column=0, sticky="w")
        self.motion_var = tk.StringVar(value="PASS")
        # 라디오 변경을 취소했을 때 되돌릴 직전 값.
        self._motion_before = "PASS"
        motions = ttk.Frame(top)
        motions.grid(row=0, column=1, sticky="w", padx=(6, 0))
        for column, name in enumerate(MOTION_PATHS):
            ttk.Radiobutton(
                motions,
                text=name,
                value=name,
                variable=self.motion_var,
                command=self._on_motion_change,
            ).grid(row=0, column=column, padx=(0, 8))

        self.status_var = tk.StringVar(value="로봇 연결 중...")
        ttk.Label(top, textvariable=self.status_var, anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        controls = ttk.LabelFrame(self, text="자세 잡기", padding=8)
        controls.grid(row=1, column=0, sticky="ew", padx=8)
        controls.columnconfigure((0, 1, 2, 3), weight=1)

        self.torque_off_button = ttk.Button(
            controls, text="Torque OFF (손으로 이동)", command=self._torque_off
        )
        self.torque_off_button.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2)
        self.torque_on_button = ttk.Button(
            controls, text="Torque ON (자세 고정)", command=self._torque_on_cmd
        )
        self.torque_on_button.grid(row=0, column=2, columnspan=2, sticky="ew", padx=2)

        self.save_pose_button = ttk.Button(
            controls, text="현재 자세 저장", command=self._save_pose
        )
        self.save_pose_button.grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=2, pady=(6, 0)
        )
        ttk.Button(
            controls, text="그리퍼 닫기 스텝", command=lambda: self._add_gripper("gripper_close")
        ).grid(row=1, column=2, sticky="ew", padx=2, pady=(6, 0))
        ttk.Button(
            controls, text="그리퍼 열기 스텝", command=lambda: self._add_gripper("gripper_open")
        ).grid(row=1, column=3, sticky="ew", padx=2, pady=(6, 0))

        sequence_box = ttk.LabelFrame(self, text="시퀀스", padding=8)
        sequence_box.grid(row=2, column=0, sticky="nsew", padx=8, pady=(6, 0))
        sequence_box.columnconfigure(0, weight=1)
        sequence_box.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(sequence_box, font="TkFixedFont")
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            sequence_box, orient="vertical", command=self.listbox.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=scrollbar.set)

        bottom = ttk.Frame(self, padding=8)
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(bottom, text="마지막 스텝 삭제", command=self._remove_last).grid(
            row=0, column=0, sticky="ew", padx=2
        )
        ttk.Button(bottom, text="기존 파일 불러오기", command=self._load_existing).grid(
            row=0, column=1, sticky="ew", padx=2
        )
        self.save_button = ttk.Button(
            bottom, text="JSON 저장", command=self._save_json
        )
        self.save_button.grid(row=0, column=2, sticky="ew", padx=2)

        self._set_hardware_buttons(enabled=False)

    # ------------------------------------------------------------------ 연결

    def _connect_worker(self) -> None:
        try:
            self.controller.connect()
            # 시작은 손으로 움직일 수 있는 상태로 — teach_motion과 같은 규약.
            self.controller.disable_torque()
        except Exception as error:
            self._notify(self._connect_failed, str(error))
            return
        self._notify(self._connect_done)

    def _notify(self, callback, *args) -> None:
        """워커 스레드에서 메인 스레드로 결과를 넘긴다.

        연결하는 몇 초 사이 사용자가 창을 닫았을 수 있다. 그때 ``after``는
        RuntimeError/TclError를 던지는데, 이미 닫힌 창에 알릴 일은 없으므로
        조용히 버린다.
        """
        try:
            self.after(0, callback, *args)
        except (RuntimeError, tk.TclError):
            pass

    def _connect_done(self) -> None:
        if not self.winfo_exists():
            return
        self._connected = True
        self._torque_on = False
        self._set_hardware_buttons(enabled=True)
        self._show_torque_state()

    def _connect_failed(self, reason: str) -> None:
        if not self.winfo_exists():
            return
        self.status_var.set(f"연결 실패: {reason}")

    def _set_hardware_buttons(self, *, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (
            self.torque_off_button,
            self.torque_on_button,
            self.save_pose_button,
        ):
            button.configure(state=state)

    def _show_torque_state(self) -> None:
        if self._torque_on:
            self.status_var.set("Torque ON — 자세가 고정됐습니다. 이제 저장할 수 있습니다.")
        else:
            self.status_var.set("Torque OFF — 로봇팔을 손으로 원하는 자세로 움직이세요.")

    # ------------------------------------------------------------------ 명령

    def _on_motion_change(self) -> None:
        selected = self.motion_var.get()
        if selected == self._motion_before:
            return
        if self.sequence and not messagebox.askyesno(
            "동작 변경",
            "동작을 바꾸면 지금 만든 시퀀스가 지워집니다. 바꿀까요?",
            parent=self,
        ):
            # 취소 — 라디오를 되돌린다. 그대로 두면 PASS로 만들던 시퀀스가
            # REJECT 파일로 저장되는 사고가 난다.
            self.motion_var.set(self._motion_before)
            return
        self._motion_before = selected
        self.sequence.clear()
        self._refresh_listbox()

    def _torque_off(self) -> None:
        try:
            self.controller.disable_torque()
        except Exception as error:
            self.status_var.set(f"토크 해제 실패: {error}")
            return
        self._torque_on = False
        self._show_torque_state()

    def _torque_on_cmd(self) -> None:
        try:
            self.controller.enable_torque()
        except Exception as error:
            self.status_var.set(f"토크 설정 실패: {error}")
            return
        self._torque_on = True
        self._show_torque_state()

    def _save_pose(self) -> None:
        if not self._torque_on:
            # OFF 상태로 읽으면 손을 떼는 순간의 흔들리는 값이 저장된다.
            messagebox.showwarning(
                "Torque OFF 상태",
                "먼저 'Torque ON (자세 고정)'으로 자세를 고정한 뒤 저장하세요.",
                parent=self,
            )
            return
        try:
            state = self.controller.read_joint_state(strict=True)
        except Exception as error:
            self.status_var.set(f"관절 읽기 실패: {error}")
            return
        self.sequence.append(
            {
                "action": "move",
                "angles": list(state.angles),
                "positions": list(state.positions),
                "duration": DEFAULT_MOVE_DURATION,
            }
        )
        self._refresh_listbox()
        self.status_var.set(
            f"스텝 {len(self.sequence)} 저장 (MOVE). 다음 자세는 Torque OFF 후 잡으세요."
        )

    def _add_gripper(self, action: str) -> None:
        self.sequence.append({"action": action, "duration": DEFAULT_GRIPPER_DURATION})
        self._refresh_listbox()

    def _remove_last(self) -> None:
        if not self.sequence:
            return
        removed = self.sequence.pop()
        self._refresh_listbox()
        self.status_var.set(f"마지막 스텝 삭제: {removed.get('action')}")

    def _refresh_listbox(self) -> None:
        self.listbox.delete(0, tk.END)
        for index, step in enumerate(self.sequence, start=1):
            self.listbox.insert(tk.END, _step_label(index, step))
        self.listbox.see(tk.END)

    # ------------------------------------------------------------------ 파일

    def _current_path(self) -> Path:
        return MOTION_PATHS[self.motion_var.get()]

    def _load_existing(self) -> None:
        path = self._current_path()
        if not path.is_file():
            messagebox.showinfo(
                "파일 없음", f"불러올 파일이 없습니다:\n{path}", parent=self
            )
            return
        if self.sequence and not messagebox.askyesno(
            "불러오기", "지금 만든 시퀀스를 버리고 파일을 불러올까요?", parent=self
        ):
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.sequence = list(data.get("sequence", []))
        except Exception as error:
            messagebox.showerror("불러오기 실패", str(error), parent=self)
            return
        self._refresh_listbox()
        self.status_var.set(f"{path.name}에서 스텝 {len(self.sequence)}개 불러옴")

    def _save_json(self) -> None:
        if not self.sequence:
            messagebox.showwarning("빈 시퀀스", "저장할 스텝이 없습니다.", parent=self)
            return
        path = self._current_path()
        # teach_motion.py와 같은 스키마 — 두 도구의 결과가 서로 호환된다.
        data = {
            "motion": self.motion_var.get(),
            "step_count": len(self.sequence),
            "sequence": self.sequence,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.status_var.set(f"저장 완료: {path.name} (스텝 {len(self.sequence)}개)")
        print(f"[분류 교시] {path}에 스텝 {len(self.sequence)}개 저장")

    # ------------------------------------------------------------------ 종료

    def _on_close(self) -> None:
        if self._closing:
            return
        if self._connected and self._torque_on:
            if not messagebox.askyesno(
                "교시 종료",
                "창을 닫으면 토크가 꺼져 팔이 처질 수 있습니다.\n"
                "팔을 잡거나 안전한 자세인지 확인했으면 닫으세요.",
                parent=self,
            ):
                return
        self._closing = True
        try:
            self.controller.disconnect()
        except Exception:
            pass
        self.destroy()
        if self.on_closed is not None:
            self.on_closed()
