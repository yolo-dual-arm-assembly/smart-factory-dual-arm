"""운영 대시보드 — 셀 장치 네 대를 한 화면에서 본다.

로봇팔 두 대(적재·분류)와 카메라 두 대(모방학습·검수)의 상태를 상단 카드에,
두 카메라 영상을 하단에 보여 준다. 모델을 시험하거나 관절을 직접 돌리는 일은
개발 도구(:mod:`system_monitor.ui.dev_console`)로 나가 있다.

이 모듈의 이름과 :func:`main`은 ``main.py``와 ``pyproject.toml``의 진입점이므로
바꾸지 않는다.

## 장치 소유권

시리얼 포트와 카메라는 배타 자원이다. 대시보드가 팔 두 대와 캠 두 대를 계속
쥐고 있으면 교시 창·캘리브레이션·비전 실행기가 같은 장치를 열지 못한다.
그래서 도구를 띄우기 전에 필요한 장치만 :meth:`release_devices`로 내주고,
도구가 끝나면 :meth:`acquire_devices`로 되찾는다. 어떤 도구가 무엇을 쓰는지는
:data:`TOOL_DEVICE_NEEDS`에 한곳으로 모아 둔다.
"""
from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from common.camera import list_cameras, selectable_devices
from common.constants import MODELS_DIR, PROJECT_DIR
from common.serial_ports import list_serial_ports
from system_monitor.ui.arm_monitor import ArmMonitor
from system_monitor.ui.camera_feed import CameraFeed
from system_monitor.ui.console import ConsolePanel, ConsoleRedirector
from system_monitor.ui.device_cards import (
    ArmStatusCard,
    CameraStatusCard,
    InspectionResultBar,
    UnavailableArmCard,
    VideoPanel,
)
from system_monitor.ui.device_roles import (
    ARM_ROLES,
    CAMERA_ROLES,
    assign_camera_roles,
    assign_omx_ports,
    camera_assignment_status,
    omx_assignment_status,
)
from system_monitor.ui.omx_panel import OmxPanel

CONSOLE_POLL_MS = 100
# 카메라 프레임 갱신 주기. 캡처(~30fps)와 어긋나며 프레임을 흘리지 않도록 절반으로 돈다.
VIEW_POLL_MS = 15
# 카드 텍스트는 사람이 읽는 값이라 자주 갱신할 필요가 없다.
CARD_POLL_MS = 400
# 대시보드의 주인공은 영상이다. 콘솔은 낮게 잡아 세로 공간을 영상에 넘긴다.
CONSOLE_HEIGHT_LINES = 6
# Text의 기본 폭 80자는 창 최소 너비를 크게 벌려 놓아 창을 줄일 수 없게 만든다.
# 콘솔은 grid로 늘어나므로 좁게 잡아도 실제 표시 폭은 남는 공간만큼 넓어진다.
CONSOLE_WIDTH_CHARS = 40
# 영상 행이 카드·도구에 밀려 납작해지지 않도록 최소 높이를 준다.
MIN_VIDEO_ROW_HEIGHT = 340

ARM_LOADING, ARM_SORTING = (role.key for role in ARM_ROLES)
CAM_IMITATION, CAM_INSPECTION = (role.key for role in CAMERA_ROLES)

# 검수 캠은 이 셀에서 직접 학습한 가중치만 쓴다.
#
# COCO 사전학습 모델(yolov8n 등)로 대체하면 안 된다 — 클래스 이름이 달라
# config/class_scheme.yaml의 ball_names와 하나도 맞지 않고, 그러면 공 개수가
# 늘 0으로 세어져 검사가 항상 REJECT로 떨어진다. 조용히 틀리느니 모델이 없다고
# 알리는 편이 낫다. 그래서 없을 때 다른 모델로 갈아타지 않는다.
INSPECTION_MODEL_PATH = MODELS_DIR / "best.pt"

# 설정 파일에서 기준 개수를 꺼 뒀을 때 스핀박스에 띄울 값.
DEFAULT_TARGET_COUNT = 1

# 도구마다 어떤 장치를 내줘야 하는지. 한곳에만 적어 두고 두 방향(release/acquire)
# 모두 이 표를 쓴다.
TOOL_DEVICE_NEEDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # 도구 이름: (놓아야 할 팔, 놓아야 할 카메라)
    "calibration": ((), (CAM_IMITATION,)),
    "teaching": ((ARM_LOADING,), (CAM_IMITATION,)),
    "mouse_approach": ((ARM_LOADING,), (CAM_IMITATION,)),
    "manual_control": ((ARM_LOADING,), ()),
    # 개발 도구는 자체 카메라 선택기로 아무 카메라나 열 수 있고, 수동 제어까지
    # 띄운다. 어느 것을 고를지 미리 알 수 없으므로 캠 두 대를 모두 내준다.
    "dev_console": ((ARM_LOADING,), (CAM_IMITATION, CAM_INSPECTION)),
}


class OperatorDashboard(tk.Tk):
    """장치 네 대의 상태와 영상을 보여 주고, 장치 소유권을 조정한다."""

    def __init__(self, inspection_model_path: Path = INSPECTION_MODEL_PATH) -> None:
        super().__init__()
        from system_monitor.ui.ui_fonts import configure_korean_fonts

        self.ui_font_family, _ = configure_korean_fonts(self)
        self.title("스마트팩토리 듀얼암 — 운영 대시보드")
        # 영상 두 칸이 16:9에 가깝게 나오는 크기로 연다. 상태카드·검사결과·
        # 도구 행이 400px쯤 쓰므로 창을 정확히 16:9로 열면 영상이 납작해진다.
        # 창을 늘리면 남는 높이는 전부 영상 행이 가져간다.
        self.geometry("1600x980")
        self.minsize(1280, 800)

        self.inspection_model_path = inspection_model_path
        self._console_redirector = ConsoleRedirector()
        self._dev_process: subprocess.Popen | None = None
        # 이름 → 그 도구가 내주게 한 장치. 되찾을 때 같은 목록을 쓴다.
        self._released_by: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        # 콤보에 올려 둔 선택 가능한 카메라 목록.
        self._camera_devices: tuple = ()

        loading_port, sorting_port = assign_omx_ports(list_serial_ports())
        self.arms: dict[str, ArmMonitor] = {
            ARM_LOADING: ArmMonitor(ARM_LOADING, loading_port),
            ARM_SORTING: ArmMonitor(ARM_SORTING, sorting_port),
        }
        self.cameras: dict[str, CameraFeed] = {
            CAM_IMITATION: CameraFeed(CAM_IMITATION, None),
            CAM_INSPECTION: CameraFeed(
                CAM_INSPECTION, None, model_path=inspection_model_path
            ),
        }

        self._build_ui()
        self._console_redirector.install()
        print(omx_assignment_status(loading_port, sorting_port))
        print(self._inspection_model_status())

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(CONSOLE_POLL_MS, self._drain_console)
        self.after(VIEW_POLL_MS, self._poll_video)
        self.after(CARD_POLL_MS, self._poll_cards)
        # 카메라 조회는 장치를 실제로 열어 보므로 창이 뜬 뒤에 시작한다.
        self.after(200, self._scan_and_start_cameras)
        for arm in self.arms.values():
            arm.start()

    @staticmethod
    def _configured_target_count() -> int:
        """설정 파일의 기준 개수. 스핀박스의 시작값이자, 다시 켰을 때 돌아갈 값이다."""
        try:
            from vision_inspection.class_scheme import load_target_count

            configured = load_target_count()
        except Exception:
            configured = None
        # 파일에서 개수 검사를 꺼 뒀으면(null) 스핀박스에는 1을 띄우되, 사용자가
        # 건드리기 전까지는 덮어쓰지 않으므로 검사는 꺼진 상태로 남는다.
        return DEFAULT_TARGET_COUNT if configured is None else configured

    def _on_target_count_change(self, value: int) -> None:
        """스핀박스에서 기준 개수를 바꿨을 때. 설정 파일은 건드리지 않는다."""
        self.cameras[CAM_INSPECTION].set_target_count(value)
        print(
            f"[검수 캠] 기준 개수 {value}개로 변경 (이번 실행에만 적용, "
            f"프로그램을 다시 켜면 설정값 {self._configured_target_count()}개로 돌아갑니다)"
        )

    def _inspection_model_status(self) -> str:
        """검수 캠이 쓸 모델을 사람이 읽을 한 줄로. 없으면 무엇을 해야 하는지 알린다."""
        path = self.inspection_model_path
        if path.is_file():
            size_mb = path.stat().st_size / 1024**2
            return f"[검수 캠] 모델 {path.name} 사용 ({size_mb:.1f} MB)"
        return (
            f"[검수 캠] 모델 없음: {path}\n"
            "  학습한 best.pt를 models/에 두어야 검사가 동작합니다. "
            "다른 모델로 대체하지 않습니다 — 클래스 이름이 달라 항상 REJECT가 됩니다."
        )

    # ------------------------------------------------------------------ UI 구성

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        # 창이 커지면 늘어나는 곳은 영상 행 하나뿐이다. 카드·검사결과·도구는
        # 내용만큼만 차지한다.
        self.rowconfigure(1, weight=1, minsize=MIN_VIDEO_ROW_HEIGHT)

        self._build_status_row()
        self._build_video_row()
        self._build_result_bar()
        self._build_tools_and_console()

    def _build_status_row(self) -> None:
        row = ttk.Frame(self, padding=(10, 10, 10, 0))
        row.grid(row=0, column=0, sticky="ew")
        for column in range(4):
            row.columnconfigure(column, weight=1, uniform="status")

        loading_role, sorting_role = ARM_ROLES
        imitation_role, inspection_role = CAMERA_ROLES

        self.arm_cards = {
            ARM_LOADING: ArmStatusCard(
                row, loading_role.title, description=loading_role.description
            ),
            # omx2_sorting은 동작이 전부 미구현이라 공정 상태를 만들어 낼 수 없다.
            ARM_SORTING: UnavailableArmCard(
                row, sorting_role.title, note="omx2_sorting 노드 미작성"
            ),
        }
        self.camera_cards = {
            CAM_IMITATION: CameraStatusCard(
                row, imitation_role.title, description=imitation_role.description
            ),
            CAM_INSPECTION: CameraStatusCard(
                row, inspection_role.title, description=inspection_role.description
            ),
        }

        for column, card in enumerate(
            (
                self.arm_cards[ARM_LOADING],
                self.arm_cards[ARM_SORTING],
                self.camera_cards[CAM_IMITATION],
                self.camera_cards[CAM_INSPECTION],
            )
        ):
            card.grid(row=0, column=column, sticky="nsew", padx=4)

    def _build_video_row(self) -> None:
        row = ttk.Frame(self, padding=(10, 10, 10, 0))
        row.grid(row=1, column=0, sticky="nsew")
        row.columnconfigure((0, 1), weight=1, uniform="video")
        row.rowconfigure(0, weight=1)
        imitation_role, inspection_role = CAMERA_ROLES
        self.video_panels = {
            CAM_IMITATION: VideoPanel(
                row, imitation_role.title, idle_text="카메라 준비 중..."
            ),
            CAM_INSPECTION: VideoPanel(
                row, inspection_role.title, idle_text="카메라 준비 중..."
            ),
        }
        self.video_panels[CAM_IMITATION].grid(
            row=0, column=0, sticky="nsew", padx=(0, 5)
        )
        self.video_panels[CAM_INSPECTION].grid(
            row=0, column=1, sticky="nsew", padx=(5, 0)
        )

    def _build_result_bar(self) -> None:
        self.result_bar = InspectionResultBar(
            self,
            font_family=self.ui_font_family,
            target_count=self._configured_target_count(),
            on_target_change=self._on_target_count_change,
        )
        self.result_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(8, 0))

    def _build_tools_and_console(self) -> None:
        bottom = ttk.Frame(self, padding=(10, 8, 10, 10))
        bottom.grid(row=3, column=0, sticky="nsew")
        # 도구를 세로로 쌓으면 이 행이 창의 절반을 먹어 영상이 눌린다.
        # OMX 도구 · 카메라 배정 · 콘솔을 가로로 나란히 둔다.
        bottom.columnconfigure(2, weight=1)

        tools = ttk.Frame(bottom)
        tools.grid(row=0, column=0, sticky="nw", padx=(0, 10))

        self.omx_panel = OmxPanel(
            tools,
            camera_busy_reason=self._camera_busy_reason,
            camera_index=lambda: self.cameras[CAM_IMITATION].index or 0,
            omx_port=lambda: self.arms[ARM_LOADING].port,
            on_tool_start=self.release_devices,
            on_tool_end=self.acquire_devices,
        )
        self.omx_panel.grid(row=0, column=0, sticky="ew")

        self.dev_button = ttk.Button(
            tools, text="개발 도구 (YOLO 시험 · 수동 제어)", command=self.open_dev_console
        )
        self.dev_button.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        # 자동 배정은 장치 열거 순서를 따를 뿐이라 두 캠이 반대로 잡히거나 한
        # 대만 잡히는 일이 흔하다. 사람이 직접 고칠 수단을 함께 둔다.
        camera_tools = ttk.LabelFrame(bottom, text="카메라 배정", padding=8)
        camera_tools.grid(row=0, column=1, sticky="nw", padx=(0, 10))
        camera_tools.columnconfigure(1, weight=1)

        self.camera_choice_vars: dict[str, tk.StringVar] = {}
        self.camera_combos: dict[str, ttk.Combobox] = {}
        for index, role in enumerate(CAMERA_ROLES):
            ttk.Label(camera_tools, text=role.title).grid(
                row=index, column=0, sticky="w", pady=2
            )
            var = tk.StringVar(value="검색 중...")
            combo = ttk.Combobox(
                camera_tools, textvariable=var, values=[], state="disabled", width=22
            )
            combo.grid(row=index, column=1, sticky="ew", padx=(6, 0), pady=2)
            combo.bind(
                "<<ComboboxSelected>>",
                lambda _event, key=role.key: self._on_camera_choice(key),
            )
            self.camera_choice_vars[role.key] = var
            self.camera_combos[role.key] = combo

        buttons = ttk.Frame(camera_tools)
        buttons.grid(row=len(CAMERA_ROLES), column=0, columnspan=2, sticky="ew", pady=(6, 0))
        buttons.columnconfigure((0, 1), weight=1)
        self.rescan_button = ttk.Button(
            buttons, text="다시 검색", command=self.rescan_cameras
        )
        self.rescan_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.swap_button = ttk.Button(
            buttons, text="역할 바꾸기", command=self.swap_camera_roles
        )
        self.swap_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.camera_status_var = tk.StringVar(value="카메라 검색 중...")
        ttk.Label(
            camera_tools,
            textvariable=self.camera_status_var,
            wraplength=280,
            anchor="w",
        ).grid(row=len(CAMERA_ROLES) + 1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # 영상이 세로로 넉넉하도록 콘솔은 낮게 둔다. 자세한 로그는 개발 도구에서 본다.
        self.console = ConsolePanel(
            bottom,
            self._console_redirector.queue,
            height=CONSOLE_HEIGHT_LINES,
            width=CONSOLE_WIDTH_CHARS,
        )
        self.console.grid(row=0, column=2, sticky="nsew")

    # ------------------------------------------------------------------ 카메라 배정

    def _scan_and_start_cameras(self) -> None:
        """연결된 카메라를 조회해 역할에 배정하고 피드를 시작한다."""
        detected = list_cameras(refresh=True)
        # 조회가 실패해도 사용자가 번호를 직접 고를 수 있어야 하므로,
        # 하나도 못 찾으면 기본 번호 목록을 대신 쓴다(CameraSelector와 같은 규칙).
        self._camera_devices = selectable_devices(detected)
        status = camera_assignment_status(detected, bool(detected))
        self.camera_status_var.set(status)
        print(status)

        labels = [device.label for device in self._camera_devices]
        for combo in self.camera_combos.values():
            combo.configure(values=labels, state="readonly" if labels else "disabled")

        imitation, inspection = assign_camera_roles(detected)
        self._apply_camera_device(CAM_IMITATION, imitation)
        self._apply_camera_device(CAM_INSPECTION, inspection)

    def _apply_camera_device(self, role_key: str, device) -> None:
        """역할 하나에 장치를 붙이고 콤보 표시를 맞춘다."""
        feed = self.cameras[role_key]
        var = self.camera_choice_vars[role_key]
        if device is None:
            feed.set_device(None)
            var.set("선택 안 됨")
            return
        feed.set_device(device.index, device.name)
        var.set(device.label)
        feed.start()

    def _device_by_label(self, label: str):
        for device in self._camera_devices:
            if device.label == label:
                return device
        return None

    def _on_camera_choice(self, role_key: str) -> None:
        """사용자가 콤보에서 카메라를 바꿨을 때."""
        if self._cameras_are_released():
            messagebox.showwarning(
                "카메라 사용 중",
                "실행 중인 OMX 도구를 먼저 종료한 뒤 바꾸세요.",
                parent=self,
            )
            return
        device = self._device_by_label(self.camera_choice_vars[role_key].get())
        if device is None:
            return
        # 두 역할이 같은 장치를 쓰면 둘 다 열리지 않는다. 겹치면 상대를 비운다.
        for other_key, other in self.cameras.items():
            if other_key != role_key and other.index == device.index:
                self._apply_camera_device(other_key, None)
                self.camera_status_var.set(
                    f"같은 카메라를 쓸 수 없어 {other_key} 역할을 비웠습니다."
                )
        self._apply_camera_device(role_key, device)

    def rescan_cameras(self) -> None:
        """카메라를 다시 조회해 역할을 재배정한다."""
        if self._cameras_are_released():
            messagebox.showwarning(
                "카메라 사용 중",
                "실행 중인 OMX 도구를 먼저 종료한 뒤 다시 검색하세요.",
                parent=self,
            )
            return
        self.camera_status_var.set("카메라 검색 중...")
        for feed in self.cameras.values():
            feed.stop()
        self._scan_and_start_cameras()

    def swap_camera_roles(self) -> None:
        """모방학습 캠과 검수 캠을 맞바꾼다.

        자동 배정은 장치 열거 순서를 따를 뿐이라 두 캠이 반대로 잡힐 수 있다.
        어느 쪽이 어느 쪽인지는 화면을 봐야 알 수 있으므로 사람이 바꾸게 한다.
        """
        if self._cameras_are_released():
            messagebox.showwarning(
                "카메라 사용 중",
                "실행 중인 OMX 도구를 먼저 종료한 뒤 바꾸세요.",
                parent=self,
            )
            return
        first = self._device_by_label(self.camera_choice_vars[CAM_IMITATION].get())
        second = self._device_by_label(self.camera_choice_vars[CAM_INSPECTION].get())
        if first is None and second is None:
            return

        # set_device는 같은 번호면 아무 일도 하지 않으므로 일단 둘 다 비운 뒤 바꾼다.
        self._apply_camera_device(CAM_IMITATION, None)
        self._apply_camera_device(CAM_INSPECTION, None)
        self._apply_camera_device(CAM_IMITATION, second)
        self._apply_camera_device(CAM_INSPECTION, first)
        self.camera_status_var.set(
            f"역할 교체됨 · 모방 {second.label if second else '없음'} · "
            f"검수 {first.label if first else '없음'}"
        )
        print("[dashboard] 카메라 역할 교체")

    def _cameras_are_released(self) -> bool:
        return any(feed.is_released for feed in self.cameras.values())

    # ------------------------------------------------------------------ 소유권 인계

    def release_devices(self, tool: str) -> None:
        """도구가 쓸 장치를 내준다. 도구를 띄우기 직전에 부른다."""
        needs = TOOL_DEVICE_NEEDS.get(tool)
        if needs is None or tool in self._released_by:
            return
        arm_keys, camera_keys = needs
        for key in arm_keys:
            self.arms[key].release()
        for key in camera_keys:
            self.cameras[key].release()
        self._released_by[tool] = needs
        if arm_keys or camera_keys:
            print(f"[dashboard] {tool}에 장치 인계: {list(arm_keys) + list(camera_keys)}")

    def acquire_devices(self, tool: str) -> None:
        """도구가 끝난 뒤 장치를 되찾는다."""
        needs = self._released_by.pop(tool, None)
        if needs is None:
            return
        arm_keys, camera_keys = needs
        for key in arm_keys:
            self.arms[key].acquire()
        for key in camera_keys:
            self.cameras[key].acquire()
        if arm_keys or camera_keys:
            print(f"[dashboard] {tool}에서 장치 회수")

    def _camera_busy_reason(self) -> str | None:
        """모방학습 캠을 도구가 쓸 수 없는 이유. 쓸 수 있으면 None."""
        if self.cameras[CAM_IMITATION].index is None:
            return "모방학습 캠이 배정되지 않았습니다. 카메라 연결을 확인하세요."
        return None

    # ------------------------------------------------------------------ 개발 도구

    def open_dev_console(self) -> None:
        if self._dev_process is not None and self._dev_process.poll() is None:
            messagebox.showinfo(
                "개발 도구 실행 중",
                "이미 열려 있는 개발 도구 창을 사용하세요.",
                parent=self,
            )
            return
        # 개발 도구가 수동 제어를 띄울 수 있으므로 적재 팔을 미리 내준다.
        self.release_devices("dev_console")
        dev_console = Path(__file__).with_name("dev_console.py")
        try:
            self._dev_process = subprocess.Popen(
                [sys.executable, str(dev_console)], cwd=PROJECT_DIR
            )
        except Exception as error:
            self.acquire_devices("dev_console")
            messagebox.showerror("개발 도구 실행 오류", str(error), parent=self)
            return
        self.dev_button.configure(state="disabled")
        self.after(300, self._poll_dev_process)

    def _poll_dev_process(self) -> None:
        process = self._dev_process
        if process is not None and process.poll() is None:
            self.after(300, self._poll_dev_process)
            return
        self._dev_process = None
        self.acquire_devices("dev_console")
        if self.winfo_exists():
            self.dev_button.configure(state="normal")

    # ------------------------------------------------------------------ 화면 갱신

    def _poll_video(self) -> None:
        if not self.winfo_exists():
            return
        for role_key, feed in self.cameras.items():
            panel = self.video_panels[role_key]
            snapshot = feed.snapshot()
            if snapshot.released:
                panel.show_message("다른 도구가 사용 중입니다.\n(실행기 창을 확인하세요)")
                panel.set_caption("")
                continue
            if snapshot.index is None:
                panel.show_message("배정된 카메라가 없습니다.")
                panel.set_caption("")
                continue
            frame = feed.take_preview()
            if frame is not None:
                panel.show_frame(frame)
            elif not snapshot.connected:
                panel.show_message(snapshot.message or "카메라 준비 중...")
            panel.set_caption(snapshot.status_text)
        self.after(VIEW_POLL_MS, self._poll_video)

    def _poll_cards(self) -> None:
        if not self.winfo_exists():
            return
        for role_key, monitor in self.arms.items():
            self.arm_cards[role_key].update_from(monitor.snapshot())
        for role_key, feed in self.cameras.items():
            self.camera_cards[role_key].update_from(feed.snapshot())
        self.result_bar.update_from(
            self.cameras[CAM_INSPECTION].snapshot().inspection
        )
        self.after(CARD_POLL_MS, self._poll_cards)

    def _drain_console(self) -> None:
        self.console.drain()
        if self.winfo_exists():
            self.after(CONSOLE_POLL_MS, self._drain_console)

    # ------------------------------------------------------------------ 종료

    def _on_close(self) -> None:
        if self._dev_process is not None and self._dev_process.poll() is None:
            messagebox.showinfo(
                "개발 도구 실행 중", "개발 도구 창을 먼저 닫아 주세요.", parent=self
            )
            return
        if not self.omx_panel.request_close(self._finish_close):
            return
        self._finish_close()

    def _finish_close(self) -> None:
        for feed in self.cameras.values():
            feed.stop()
        # 감시자는 토크를 켠 적이 없으므로 여기서 연결을 끊어도 팔은 떨어지지 않는다.
        for arm in self.arms.values():
            arm.stop()
        self._console_redirector.restore()
        self.destroy()


def main() -> None:
    app = OperatorDashboard()
    app.mainloop()


if __name__ == "__main__":
    main()
