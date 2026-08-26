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
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from common.camera import list_cameras, selectable_devices
from common.constants import MODELS_DIR, OMX_CALIBRATION_PATH, PROJECT_DIR
from common.messages import InspectionResult, RobotStatus
from common.omx_controller import OmxConfig, OmxController
from common.serial_ports import list_serial_ports
from system_monitor.ui.arm_monitor import ArmMonitor
from system_monitor.ui.camera_feed import CameraFeed
from system_monitor.ui.console import ConsolePanel, ConsoleRedirector
from system_monitor.ui.device_cards import (
    COLOR_ERROR,
    ArmStatusCard,
    CameraStatusCard,
    InspectionResultBar,
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
from system_monitor.ui.integrated_process import (
    DeviceAvailability,
    ProcessCancelled,
    ProcessPlan,
    build_process_plan,
    run_process_cycle,
)
from system_monitor.ui.omx_panel import OmxPanel
from system_monitor.ui.sorting_panel import (
    TOOL_MOTION as SORTING_MOTION,
    TOOL_TEACHING as SORTING_TEACHING,
    SortingPanel,
    execute_sorting_motion,
)

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
# 새 검사 판정이 안정화되기를 기다리는 최대 시간. 정상 상태에서는 안정화
# 게이트(1초, 3표본)가 먼저 끝나고, 모델/카메라가 멈췄을 때만 이 제한에 닿는다.
INSPECTION_TIMEOUT_SEC = 15.0
INSPECTION_POLL_SEC = 0.1
TOOL_INTEGRATED = "integrated_process"

ARM_LOADING, ARM_SORTING = (role.key for role in ARM_ROLES)
CAM_IMITATION, CAM_INSPECTION = (role.key for role in CAMERA_ROLES)

# 검수 캠은 이 셀에서 직접 학습한 가중치만 쓴다.
#
# COCO 사전학습 모델(yolov8n 등)로 대체하면 안 된다 — 클래스 이름이 달라
# config/class_scheme.yaml의 ball_names와 하나도 맞지 않고, 그러면 공 개수가
# 늘 0으로 세어져 검사가 항상 REJECT로 떨어진다. 조용히 틀리느니 모델이 없다고
# 알리는 편이 낫다. 그래서 없을 때 다른 모델로 갈아타지 않는다.
INSPECTION_MODEL_PATH = MODELS_DIR / "best.pt"

# 검수 판정과는 무관한, 독립된 두 번째 추론이다. COCO 사전학습 모델을 그대로
# 쓰며 위 INSPECTION_MODEL_PATH를 대체하지 않는다 — 사람(class 0)만 걸러
# 화면에 경고만 띄운다(로봇 정지 연동 없음). vision_inspection의 모델 다운로드
# 목록에 이미 등록돼 있어 없으면 그쪽에서 받으면 된다.
PERSON_MODEL_PATH = MODELS_DIR / "yolov8n.pt"
# 경고 팝업 배경색. 눈에 띄어야 하므로 카드/라벨에 쓰는 COLOR_WARN(연한 황색)이
# 아니라 더 강한 COLOR_ERROR를 쓴다.
PERSON_WARNING_BG = COLOR_ERROR

# 설정 파일에서 기준 개수를 꺼 뒀을 때 스핀박스에 띄울 값.
DEFAULT_TARGET_COUNT = 1

# 도구마다 어떤 장치를 내줘야 하는지. 한곳에만 적어 두고 두 방향(release/acquire)
# 모두 이 표를 쓴다.
TOOL_DEVICE_NEEDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # 도구 이름: (놓아야 할 팔, 놓아야 할 카메라)
    "manual_control": ((ARM_LOADING,), ()),
    # 카메라 캘리브레이션 창은 모방학습 캠만 직접 열어서 쓴다 — 팔 포트는
    # 안 건드린다(OmxCalibrationWindow는 화면 클릭+좌표 입력만 함).
    "omx1_calibration": ((), (CAM_IMITATION,)),
    # 개발 도구는 자체 카메라 선택기로 아무 카메라나 열 수 있고, 수동 제어까지
    # 띄운다. 어느 것을 고를지 미리 알 수 없으므로 캠 두 대를 모두 내준다.
    "dev_console": ((ARM_LOADING,), (CAM_IMITATION, CAM_INSPECTION)),
    # 분류(OMX 2) 도구는 분류 팔만 쓴다. 카메라는 건드리지 않는다.
    SORTING_MOTION: ((ARM_SORTING,), ()),
    SORTING_TEACHING: ((ARM_SORTING,), ()),
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
        # 콘솔에 마지막으로 찍은 확정 판정. 같은 판정을 두 번 찍지 않으려고 들고 있다.
        self._logged_verdict: tuple | None = None
        self._integrated_thread: threading.Thread | None = None
        self._integrated_cancel = threading.Event()
        # 중단 버튼이 현재 단계에 즉시 요청을 전달할 수 있게 워커가 채운다.
        self._integrated_loading_runner = None
        self._integrated_sorting_controller: OmxController | None = None

        loading_port, sorting_port = assign_omx_ports(list_serial_ports())
        self.arms: dict[str, ArmMonitor] = {
            ARM_LOADING: ArmMonitor(ARM_LOADING, loading_port),
            ARM_SORTING: ArmMonitor(ARM_SORTING, sorting_port),
        }
        self.cameras: dict[str, CameraFeed] = {
            CAM_IMITATION: CameraFeed(CAM_IMITATION, None),
            CAM_INSPECTION: CameraFeed(
                CAM_INSPECTION,
                None,
                model_path=inspection_model_path,
                person_model_path=(
                    PERSON_MODEL_PATH if PERSON_MODEL_PATH.is_file() else None
                ),
            ),
        }

        self._build_ui()
        self._console_redirector.install()
        print(omx_assignment_status(loading_port, sorting_port))
        print(self._inspection_model_status())
        print(self._person_model_status())

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

    def _on_safe_mode_toggle(self) -> None:
        """세이프 모드 체크박스에서. 꺼지면 이미 뜬 경고도 즉시 지운다."""
        enabled = self.safe_mode_var.get()
        self.cameras[CAM_INSPECTION].set_person_detection_enabled(enabled)
        if not enabled:
            self._hide_person_warning()
        print(f"[검수 캠] 세이프 모드(사람 감지) {'켜짐' if enabled else '꺼짐'}")

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

    @staticmethod
    def _person_model_status() -> str:
        """검수 캠 사람 감지 경고에 쓸 모델 상태를 한 줄로. 없으면 조용히 꺼진다."""
        if PERSON_MODEL_PATH.is_file():
            return f"[검수 캠] 사람 감지 모델 {PERSON_MODEL_PATH.name} 사용"
        return (
            f"[검수 캠] 사람 감지 모델 없음: {PERSON_MODEL_PATH} — 경고 기능 비활성화"
            " (개발 도구의 모델 다운로드로 받을 수 있습니다)"
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
        self._build_person_warning()
        self._build_integrated_bar()
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
            # PASS/REJECT 웨이포인트 동작이 들어와 분류 팔도 일반 카드로 승격했다.
            ARM_SORTING: ArmStatusCard(
                row, sorting_role.title, description=sorting_role.description
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

    def _build_person_warning(self) -> None:
        """검수 캠에 사람이 잡히면 뜨는 큰 경고 팝업. 로봇 정지 연동은 없다(표시만).

        폴링마다 새로 만들지 않고 하나만 만들어 두고 deiconify/withdraw로
        여닫는다 — 계속 반복되는 상태 표시라 messagebox처럼 매번 확인을
        요구하면 오히려 방해가 된다.
        """
        popup = tk.Toplevel(self)
        popup.title("⚠ 경고")
        popup.configure(background=PERSON_WARNING_BG)
        popup.attributes("-topmost", True)
        # 사용자가 닫아도 다음 폴링에서 사람이 여전히 잡히면 다시 뜬다 —
        # 그래서 destroy 대신 숨기기만 한다.
        popup.protocol("WM_DELETE_WINDOW", popup.withdraw)
        popup.withdraw()

        # ttk.Label의 background는 테마에 따라 무시될 수 있어(활성 테마가 배경을
        # 덮어씀), 색이 반드시 먹어야 하는 이 경고는 일반 tk.Label을 쓴다.
        self.person_warning_var = tk.StringVar(value="")
        tk.Label(
            popup,
            textvariable=self.person_warning_var,
            font=(self.ui_font_family, 28, "bold"),
            fg="white",
            bg=PERSON_WARNING_BG,
            anchor="center",
            justify="center",
            padx=40,
            pady=40,
            wraplength=560,
        ).pack(fill="both", expand=True)
        self.person_warning_popup = popup

    def _show_person_warning(self, count: int) -> None:
        self.person_warning_var.set(
            f"⚠ 위험\n검수 구역에 사람 감지됨 ({count}명)"
        )
        popup = self.person_warning_popup
        if not popup.winfo_viewable():
            self.update_idletasks()
            width, height = 640, 260
            x = self.winfo_rootx() + (self.winfo_width() - width) // 2
            y = self.winfo_rooty() + (self.winfo_height() - height) // 2
            popup.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
            popup.deiconify()
            popup.lift()

    def _hide_person_warning(self) -> None:
        self.person_warning_popup.withdraw()

    def _build_integrated_bar(self) -> None:
        bar = ttk.LabelFrame(self, text="통합 공정", padding=(10, 6))
        bar.grid(row=3, column=0, sticky="ew", padx=10, pady=(8, 0))
        bar.columnconfigure(2, weight=1)

        self.integrated_button = ttk.Button(
            bar, text="▶ 통합 공정 실행", command=self.start_integrated_process
        )
        self.integrated_button.grid(row=0, column=0, sticky="w")
        self.integrated_stop_button = ttk.Button(
            bar,
            text="중단",
            command=self.stop_integrated_process,
            state="disabled",
        )
        self.integrated_stop_button.grid(row=0, column=1, sticky="w", padx=(8, 12))
        self.integrated_status_var = tk.StringVar(
            value="대기 · OMX1 적재 → 비전 검사 → OMX2 분류"
        )
        ttk.Label(
            bar, textvariable=self.integrated_status_var, anchor="w", wraplength=900
        ).grid(row=0, column=2, sticky="ew")

    def _build_tools_and_console(self) -> None:
        bottom = ttk.Frame(self, padding=(10, 8, 10, 10))
        bottom.grid(row=4, column=0, sticky="nsew")
        # 도구를 세로로 쌓으면 이 행이 창의 절반을 먹어 영상이 눌린다.
        # OMX1 도구 · OMX2 분류 · 카메라 배정 · 콘솔을 가로로 나란히 둔다.
        bottom.columnconfigure(3, weight=1)

        tools = ttk.Frame(bottom)
        tools.grid(row=0, column=0, sticky="nw", padx=(0, 10))

        self.omx_panel = OmxPanel(
            tools,
            omx_port=lambda: self.arms[ARM_LOADING].port,
            on_tool_start=self.release_devices,
            on_tool_end=self.acquire_devices,
            on_calibrate=self.open_omx1_calibration,
        )
        self.omx_panel.grid(row=0, column=0, sticky="ew")

        self.dev_button = ttk.Button(
            tools, text="개발 도구 (YOLO 시험 · 수동 제어)", command=self.open_dev_console
        )
        self.dev_button.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self.sorting_panel = SortingPanel(
            bottom,
            omx_port=lambda: self.arms[ARM_SORTING].port,
            on_tool_start=self.release_devices,
            on_tool_end=self.acquire_devices,
        )
        self.sorting_panel.grid(row=0, column=1, sticky="nw", padx=(0, 10))

        self.swap_arm_button = ttk.Button(
            tools, text="OMX 1↔2 포트 바꾸기", command=self.swap_arm_roles
        )
        self.swap_arm_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        self.safe_mode_var = tk.BooleanVar(value=True)
        self.safe_mode_check = ttk.Checkbutton(
            tools,
            text="세이프 모드 (검수 캠 사람 감지 경고)",
            variable=self.safe_mode_var,
            command=self._on_safe_mode_toggle,
        )
        self.safe_mode_check.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        if not PERSON_MODEL_PATH.is_file():
            # 모델이 없으면 애초에 켤 게 없다 — 상태를 정직하게 반영한다.
            self.safe_mode_var.set(False)
            self.safe_mode_check.configure(state="disabled")

        # 자동 배정은 장치 열거 순서를 따를 뿐이라 두 캠이 반대로 잡히거나 한
        # 대만 잡히는 일이 흔하다. 사람이 직접 고칠 수단을 함께 둔다.
        camera_tools = ttk.LabelFrame(bottom, text="카메라 배정", padding=8)
        camera_tools.grid(row=0, column=2, sticky="nw", padx=(0, 10))
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
        self.console.grid(row=0, column=3, sticky="nsew")

    # ------------------------------------------------------------------ 통합 공정

    def _integrated_is_running(self) -> bool:
        thread = self._integrated_thread
        return thread is not None and thread.is_alive()

    def _device_availability(self) -> DeviceAvailability:
        """카드에 표시하는 것과 같은 스냅샷으로 네 장치를 한 번에 확인한다."""
        loading = self.arms[ARM_LOADING].snapshot()
        sorting = self.arms[ARM_SORTING].snapshot()
        imitation = self.cameras[CAM_IMITATION].snapshot()
        inspection = self.cameras[CAM_INSPECTION].snapshot()
        return DeviceAvailability(
            omx1=loading.connected and not loading.released,
            omx2=sorting.connected and not sorting.released,
            imitation_camera=imitation.connected and not imitation.released,
            inspection_camera=inspection.connected and not inspection.released,
        )

    def start_integrated_process(self) -> None:
        """장치 확인 후 가능한 적재·검사·분류 단계를 워커에서 순차 실행한다."""
        if self._integrated_is_running():
            return
        if (
            self.omx_panel.is_busy()
            or self.sorting_panel.is_busy()
            or (self._dev_process is not None and self._dev_process.poll() is None)
            or bool(self._released_by)
        ):
            messagebox.showwarning(
                "다른 작업 실행 중",
                "수동 제어·분류·개발 도구를 먼저 종료한 뒤 통합 공정을 실행하세요.",
                parent=self,
            )
            return

        devices = self._device_availability()
        model_ready = self.inspection_model_path.is_file()
        calibration_ready = OMX_CALIBRATION_PATH.is_file()
        plan = build_process_plan(
            devices,
            loading_configured=model_ready and calibration_ready,
            inspection_configured=model_ready,
        )

        unavailable = list(devices.missing_labels())
        if not calibration_ready:
            unavailable.append("OMX 1 좌표 보정 파일")
        if not model_ready:
            unavailable.append("YOLO 검사/적재 모델")

        if unavailable:
            missing_text = "\n".join(f"- {label}" for label in unavailable)
            if not messagebox.askyesno(
                "일부 장치·설정 없음",
                "다음 항목을 사용할 수 없습니다.\n\n"
                f"{missing_text}\n\n"
                "관련 단계는 건너뛰고 가능한 단계만 순서대로 실행할까요?\n"
                "실행 전 두 로봇의 작업 영역이 비어 있는지 확인하세요.",
                parent=self,
                default=messagebox.NO,
            ):
                return
        elif not messagebox.askyesno(
            "통합 공정 실행",
            "OMX1 적재 → 비전 검사 → OMX2 분류를 실제로 한 번 실행합니다.\n\n"
            "두 로봇의 작업 영역이 비어 있고 비상정지가 가능한 상태입니까?",
            parent=self,
            default=messagebox.NO,
        ):
            return

        if not plan.has_runnable_stage:
            summary = ", ".join(f"{stage}({reason})" for stage, reason in plan.skipped)
            self.integrated_status_var.set("실행 가능한 단계 없음")
            print(f"[통합 공정] 실행 가능한 단계 없음 · {summary}")
            return

        loading_port = self.arms[ARM_LOADING].port
        sorting_port = self.arms[ARM_SORTING].port
        imitation_index = self.cameras[CAM_IMITATION].index
        self._integrated_cancel.clear()
        self._set_integrated_busy(True)
        self._release_integrated_devices(plan)

        skipped = ", ".join(stage for stage, _reason in plan.skipped)
        if skipped:
            print(f"[통합 공정] 건너뜀: {skipped}")
        self.integrated_status_var.set("통합 공정 시작 중...")
        self._integrated_thread = threading.Thread(
            target=self._integrated_worker,
            args=(plan, loading_port, sorting_port, imitation_index),
            name="integrated-process",
            daemon=True,
        )
        self._integrated_thread.start()

    def _release_integrated_devices(self, plan: ProcessPlan) -> None:
        """이번 계획이 실제로 쓰는 배타 장치만 대시보드 감시에서 해제한다."""
        arm_keys: list[str] = []
        camera_keys: list[str] = []
        if plan.run_loading:
            arm_keys.append(ARM_LOADING)
            camera_keys.append(CAM_IMITATION)
        if plan.run_sorting:
            arm_keys.append(ARM_SORTING)
        needs = (tuple(arm_keys), tuple(camera_keys))
        for key in arm_keys:
            self.arms[key].release()
        for key in camera_keys:
            self.cameras[key].release()
        self._released_by[TOOL_INTEGRATED] = needs
        if arm_keys or camera_keys:
            print(
                "[dashboard] 통합 공정에 장치 인계: "
                f"{arm_keys + camera_keys}"
            )

    def _integrated_worker(
        self,
        plan: ProcessPlan,
        loading_port: str | None,
        sorting_port: str | None,
        imitation_index: int | None,
    ) -> None:
        def run_loading() -> None:
            if loading_port is None or imitation_index is None:
                raise RuntimeError("OMX1 적재 장치 배정이 실행 직전에 사라졌습니다.")
            self._run_loading_once(loading_port, imitation_index)

        def run_sorting(inspection: InspectionResult) -> RobotStatus:
            if sorting_port is None:
                raise RuntimeError("OMX2 포트 배정이 실행 직전에 사라졌습니다.")
            return self._run_sorting_once(sorting_port, inspection)

        try:
            result = run_process_cycle(
                plan,
                run_loading=run_loading,
                wait_for_inspection=self._wait_for_fresh_inspection,
                run_sorting=run_sorting,
                set_status=self._set_integrated_status,
                is_cancelled=self._integrated_cancel.is_set,
                inspection_timeout_sec=INSPECTION_TIMEOUT_SEC,
            )
        finally:
            self._integrated_loading_runner = None
            self._integrated_sorting_controller = None
        try:
            self.after(
                0,
                self._integrated_done,
                result.status,
                result.completed,
                result.detail,
                plan,
            )
        except (RuntimeError, tk.TclError):
            pass

    def _run_loading_once(self, port: str, camera_index: int) -> None:
        """기존 OMX1 Pick & Place 실행기를 첫 동작 뒤 종료되도록 감싼다."""
        from omx1_loading.coordinate_transform import OmxCalibration
        from omx1_loading.pick_ball import OmxVisionRunner, State

        dashboard = self

        class OneCycleVisionRunner(OmxVisionRunner):
            cycle_completed = False

            def _execute_action(
                self, robot_xyz: tuple[float, float, float]
            ) -> None:
                super()._execute_action(robot_xyz)
                self.cycle_completed = True
                self.request_stop()

        calibration = OmxCalibration.load(OMX_CALIBRATION_PATH)
        runner = OneCycleVisionRunner(
            model_path=self.inspection_model_path,
            calibration=calibration,
            config=OmxConfig(port=port),
            target_class=None,
            confidence=0.5,
            camera_index=camera_index,
            max_stage=State.HOME,
        )
        dashboard._integrated_loading_runner = runner
        if self._integrated_cancel.is_set():
            raise ProcessCancelled
        runner.run()
        if not runner.cycle_completed:
            raise RuntimeError(
                "물체를 적재하기 전에 OMX1 비전 실행이 종료되었습니다."
            )

    def _wait_for_fresh_inspection(self) -> InspectionResult | None:
        feed = self.cameras[CAM_INSPECTION]
        feed.reset_inspection()
        deadline = time.monotonic() + INSPECTION_TIMEOUT_SEC
        while time.monotonic() < deadline:
            self._raise_if_integrated_cancelled()
            snapshot = feed.snapshot()
            if not snapshot.connected or snapshot.released:
                raise RuntimeError(snapshot.message or "검수 캠 연결이 끊겼습니다.")
            if snapshot.inspection is not None and not snapshot.settling:
                return snapshot.inspection
            self._integrated_cancel.wait(INSPECTION_POLL_SEC)
        return None

    def _run_sorting_once(
        self, port: str, inspection: InspectionResult
    ) -> RobotStatus:
        controller = OmxController(OmxConfig(port=port))
        self._integrated_sorting_controller = controller
        try:
            controller.connect()
            return execute_sorting_motion(controller, inspection)
        finally:
            try:
                controller.disconnect()
            except Exception:
                pass
            self._integrated_sorting_controller = None

    def _raise_if_integrated_cancelled(self) -> None:
        if self._integrated_cancel.is_set():
            raise ProcessCancelled

    def _set_integrated_status(self, text: str) -> None:
        try:
            self.after(0, self.integrated_status_var.set, text)
        except (RuntimeError, tk.TclError):
            pass

    def stop_integrated_process(self) -> None:
        if not self._integrated_is_running():
            return
        self._integrated_cancel.set()
        runner = self._integrated_loading_runner
        if runner is not None:
            runner.request_stop()
            # request_stop은 탐지 루프를 멈춘다. 이미 팔이 이동 중이면 공용
            # 컨트롤러에도 요청해 다음 보간 지점에서 실제 모션을 중단한다.
            runner.controller.request_stop()
        controller = self._integrated_sorting_controller
        if controller is not None:
            controller.request_stop()
        self.integrated_stop_button.configure(state="disabled")
        self.integrated_status_var.set("중단 요청됨 — 현재 동작 정리 중...")

    def _set_integrated_busy(self, busy: bool) -> None:
        self.integrated_button.configure(state="disabled" if busy else "normal")
        self.integrated_stop_button.configure(state="normal" if busy else "disabled")
        self.omx_panel.set_external_busy(busy)
        self.sorting_panel.set_external_busy(busy)
        state = "disabled" if busy else "normal"
        for button in (
            self.dev_button,
            self.swap_arm_button,
            self.rescan_button,
            self.swap_button,
        ):
            button.configure(state=state)
        for combo in self.camera_combos.values():
            idle_state = "readonly" if self._camera_devices else "disabled"
            combo.configure(
                state="disabled" if busy else idle_state
            )

    def _integrated_done(
        self,
        outcome: str,
        completed: tuple[str, ...],
        detail: str,
        plan: ProcessPlan,
    ) -> None:
        self._integrated_thread = None
        self.acquire_devices(TOOL_INTEGRATED)
        self._set_integrated_busy(False)
        completed_text = " → ".join(completed) if completed else "완료 단계 없음"
        skipped_text = ", ".join(stage for stage, _reason in plan.skipped)
        if outcome == "completed":
            suffix = f" · 건너뜀: {skipped_text}" if skipped_text else ""
            self.integrated_status_var.set(f"완료 · {completed_text}{suffix}")
        elif outcome == "partial":
            self.integrated_status_var.set(f"부분 완료 · {completed_text} · {detail}")
            messagebox.showwarning("통합 공정 부분 완료", detail, parent=self)
        elif outcome == "cancelled":
            self.integrated_status_var.set(f"중단됨 · {completed_text}")
        else:
            self.integrated_status_var.set(f"실패 · {detail}")
            messagebox.showerror("통합 공정 실패", detail, parent=self)

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

    def swap_arm_roles(self) -> None:
        """OMX 1(적재)·OMX 2(분류)의 포트 배정을 맞바꾼다.

        자동 배정은 포트 열거 순서를 따를 뿐이라 부팅에 따라 두 팔이 반대로
        잡힐 수 있다. 어느 보드가 어느 팔인지는 실물을 봐야 알 수 있으므로
        사람이 바꾸게 한다. 보드가 하나뿐일 때 분류 팔을 시험하고 싶으면 그
        포트를 OMX 2로 넘기는 용도로도 쓴다.
        """
        loading = self.arms[ARM_LOADING]
        sorting = self.arms[ARM_SORTING]
        if loading.is_released or sorting.is_released:
            messagebox.showwarning(
                "로봇팔 사용 중",
                "실행 중인 도구(교시·분류 동작 등)를 먼저 종료한 뒤 바꾸세요.",
                parent=self,
            )
            return
        loading_port, sorting_port = loading.port, sorting.port
        if loading_port is None and sorting_port is None:
            messagebox.showinfo("포트 없음", "바꿀 포트가 없습니다.", parent=self)
            return

        # 서로의 포트를 바로 배정하면 상대 감시자가 아직 그 포트를 쥐고 있어
        # 연결이 충돌한다. 카메라 교체와 같은 이유로 둘 다 비운 뒤 바꾼다.
        loading.set_port(None)
        sorting.set_port(None)
        loading.set_port(sorting_port)
        sorting.set_port(loading_port)

        self.omx_panel.refresh_port()
        self.sorting_panel.refresh_port()
        print(
            f"[dashboard] OMX 포트 교체 · OMX 1={sorting_port or '없음'} · "
            f"OMX 2={loading_port or '없음'}"
        )

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
        if self.winfo_exists() and not self._integrated_is_running():
            self.dev_button.configure(state="normal")

    def open_omx1_calibration(self) -> None:
        """모방학습 캠으로 OMX1 카메라 캘리브레이션 창을 연다.

        이 창은 subprocess가 아니라 대시보드 안에서 직접 여는 Toplevel이라,
        상시 실행 중인 모방학습 캠 CameraFeed와 같은 장치를 동시에 열면
        충돌한다. 그래서 다른 도구들과 같은 release/acquire 인계를 쓴다.
        """
        if (
            self._integrated_is_running()
            or self.omx_panel.is_busy()
            or self.sorting_panel.is_busy()
            or (self._dev_process is not None and self._dev_process.poll() is None)
            or bool(self._released_by)
        ):
            messagebox.showwarning(
                "다른 작업 실행 중",
                "통합 공정·수동 제어·분류·개발 도구를 먼저 종료한 뒤 "
                "캘리브레이션을 여세요.",
                parent=self,
            )
            return

        index = self.cameras[CAM_IMITATION].index
        if index is None:
            messagebox.showerror(
                "카메라 없음",
                "모방학습 캠이 배정되지 않았습니다. 카메라 배정을 먼저 확인하세요.",
                parent=self,
            )
            return

        self.release_devices("omx1_calibration")
        self.omx_panel.set_calibration_active(True)
        from omx1_loading.camera_calibration import OmxCalibrationWindow

        def on_closed() -> None:
            self.acquire_devices("omx1_calibration")
            if self.winfo_exists():
                self.omx_panel.set_calibration_active(False)

        try:
            OmxCalibrationWindow(
                self,
                camera_index=index,
                save_path=OMX_CALIBRATION_PATH,
                on_closed=on_closed,
            )
        except Exception as error:
            self.acquire_devices("omx1_calibration")
            self.omx_panel.set_calibration_active(False)
            messagebox.showerror("카메라 오류", str(error), parent=self)

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
        inspection_snapshot = self.cameras[CAM_INSPECTION].snapshot()
        self.result_bar.update_from(
            inspection_snapshot.inspection, settling=inspection_snapshot.settling
        )
        self._log_verdict_change(inspection_snapshot.inspection)
        if inspection_snapshot.person_detected:
            self._show_person_warning(inspection_snapshot.person_count)
        else:
            self._hide_person_warning()
        self.after(CARD_POLL_MS, self._poll_cards)

    def _log_verdict_change(self, result: InspectionResult | None) -> None:
        """확정 판정이 바뀐 순간에만 콘솔에 한 줄 남긴다.

        여기 들어오는 값은 안정화 게이트(:mod:`vision_inspection.stability`)가
        래치한 **확정** 판정이라, 개수가 흔들리는 동안에는 바뀌지 않는다. 그래서
        전이만 걸러도 로그가 튀지 않는다. 흔들리는 중이라는 사실은 화면의
        "안정화 중…" 표시가 맡고, 콘솔에는 확정된 것만 남긴다.

        개수가 달라진 것도 전이로 치기 때문에 PASS가 이어져도 공이 늘거나 줄면
        다시 찍힌다.
        """
        key = (
            None
            if result is None
            else (result.result, result.total_count, result.defect_count)
        )
        if key == self._logged_verdict:
            return
        self._logged_verdict = key
        # 카메라가 빠지거나 검수 캠이 비면 None이 된다. 판정이 아니므로 찍지 않되,
        # 다시 붙었을 때 첫 판정은 새 전이로 남도록 위에서 기록만 해 둔다.
        if result is None:
            return
        print(
            f"{time.strftime('%H:%M:%S')} [검수] {result.result} — "
            f"{self._verdict_reason(result)}"
        )

    def _verdict_reason(self, result: InspectionResult) -> str:
        """판정 이유 한 줄. 기준 개수는 검수 캠이 실제로 쓰는 값을 그대로 쓴다."""
        try:
            from vision_inspection.inspection_logic import UNSET, verdict_reason

            override = self.cameras[CAM_INSPECTION].target_count
            # 덮어쓴 값이 없으면 UNSET을 넘겨 설정 파일 값을 쓰게 한다.
            # None은 '개수 검사 끄기'라는 다른 뜻이라 그대로 넘기면 안 된다.
            return verdict_reason(result, UNSET if override is None else override)
        except Exception:
            # 이유를 못 만들어도 판정 자체는 알려 준다.
            return f"총 {result.total_count}개, 불량 {result.defect_count}개"

    def _drain_console(self) -> None:
        self.console.drain()
        if self.winfo_exists():
            self.after(CONSOLE_POLL_MS, self._drain_console)

    # ------------------------------------------------------------------ 종료

    def _on_close(self) -> None:
        if self._integrated_is_running():
            if messagebox.askyesno(
                "통합 공정 실행 중",
                "통합 공정을 중단할까요?\n"
                "현재 로봇 동작을 안전하게 정리한 뒤 창을 다시 닫아 주세요.",
                parent=self,
                default=messagebox.NO,
            ):
                self.stop_integrated_process()
            return
        if self._dev_process is not None and self._dev_process.poll() is None:
            messagebox.showinfo(
                "개발 도구 실행 중", "개발 도구 창을 먼저 닫아 주세요.", parent=self
            )
            return
        if not self.sorting_panel.request_close():
            return
        if not self.omx_panel.request_close():
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
