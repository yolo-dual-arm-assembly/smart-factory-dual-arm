"""개발·시험용 GUI.

운영 대시보드(:mod:`system_monitor.ui.viewer`)에서 떼어낸 도구 모음이다.
공정을 지켜보는 화면과 모델을 시험하는 화면은 쓰는 사람도 쓰는 때도 달라서
한 창에 있으면 서로 방해한다.

여기 있는 것:

- YOLO 이미지 분석 (``object/`` 이미지를 모델별로 변환 전/후 비교)
- 웹캠 실시간 탐지와 스냅샷
- OMX 수동 관절 제어 (별도 프로세스)

실행 방법 두 가지 모두 지원한다.

    python -m system_monitor.ui.dev_console
    # 또는 대시보드의 "개발 도구" 버튼

대시보드와 카메라·로봇을 동시에 쓰면 장치를 서로 뺏으므로, 대시보드가 이 창을
띄울 때는 필요한 장치를 먼저 내려놓는다.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox, ttk

# 대시보드가 이 파일을 별도 프로세스로 띄우고, `python -m ...`이나 VS Code의
# "Run Python File"로도 실행한다. 어느 쪽이든 vision_inspection까지 import
# 경로에 있어야 하므로, common을 먼저 올린 뒤 워크스페이스 전체를 등록한다.
_WORKSPACE_SRC = Path(__file__).resolve().parents[3]
if str(_WORKSPACE_SRC / "common") not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_SRC / "common"))
from common.bootstrap import ensure_workspace_path  # noqa: E402

ensure_workspace_path()

from PIL import Image, ImageOps, ImageTk  # noqa: E402
from ultralytics import YOLO  # noqa: E402

from common.constants import (  # noqa: E402
    IMAGE_EXTENSIONS,
    INPUT_DIR,
    MODELS_DIR,
    OUTPUT_DIR,
    PREVIEW_SIZE,
    PROJECT_DIR,
)
from common.serial_ports import list_serial_ports  # noqa: E402
from system_monitor.ui.camera_select import CameraSelector  # noqa: E402
from system_monitor.ui.console import ConsolePanel, ConsoleRedirector  # noqa: E402
from system_monitor.ui.device_roles import (  # noqa: E402
    assign_omx_ports,
    fallback_omx_port,
)
from system_monitor.ui.ui_fonts import configure_korean_fonts  # noqa: E402
from system_monitor.ui.webcam import WebcamWindow  # noqa: E402
from vision_inspection.analysis import run_analysis  # noqa: E402
from vision_inspection.models import (  # noqa: E402
    DEFAULT_MODEL_FILENAME,
    MODEL_SPECS,
    SPECS_BY_LABEL,
    available_model_specs,
    download_model,
    missing_model_paths,
)

CONSOLE_POLL_MS = 100
SCANNING_MESSAGE = "연결된 카메라를 확인하는 중입니다. 잠시 후 다시 시도하세요."


class DevConsoleApp(tk.Tk):
    """모델 시험과 장비 수동 조작을 모아 둔 개발용 창."""

    def __init__(
        self, input_dir: Path = INPUT_DIR, output_dir: Path = OUTPUT_DIR
    ) -> None:
        super().__init__()
        self.ui_font_family, _ = configure_korean_fonts(self)
        self.title("개발 도구 — YOLO 시험 · 수동 관절 제어")
        self.geometry("1500x850")
        self.minsize(1050, 650)

        self.input_dir = input_dir
        self.output_dir = output_dir
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.image_paths: list[Path] = []
        # Tk PhotoImage는 파이썬 참조가 사라지면 GC되어 화면에서 지워지므로
        # 인스턴스 필드로 강한 참조를 유지한다.
        self.original_photo: ImageTk.PhotoImage | None = None
        self.result_photo: ImageTk.PhotoImage | None = None
        self.model: YOLO | None = None
        self.loaded_model_path: Path | None = None
        self.processing = False
        self.available_specs = available_model_specs()
        default_label = next(
            spec.label
            for spec in self.available_specs
            if spec.filename == DEFAULT_MODEL_FILENAME
        )
        self.model_choice = tk.StringVar(value=default_label)
        self.webcam_window: WebcamWindow | None = None
        self.camera_selector: CameraSelector | None = None
        self._manual_process: subprocess.Popen | None = None
        self._console_redirector = ConsoleRedirector()

        self._build_ui()
        self._console_redirector.install()
        for spec in MODEL_SPECS:
            if spec not in self.available_specs:
                print(
                    f"[model unavailable] {spec.filename} 없음 — "
                    "python -m vision_inspection.train으로 학습하면 해당 모델이 활성화됩니다."
                )
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(CONSOLE_POLL_MS, self._drain_console)
        self.refresh_images()
        self.after(100, self._prepare_models)

    # ------------------------------------------------------------------ UI 구성

    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self._build_sidebar()
        self._build_compare_panel()
        self._build_console()

    def _build_sidebar(self) -> None:
        sidebar = ttk.Frame(self, padding=10)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.rowconfigure(3, weight=1)

        ttk.Label(
            sidebar, text="모델 선택", font=(self.ui_font_family, 12, "bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.model_combo = ttk.Combobox(
            sidebar,
            textvariable=self.model_choice,
            values=[spec.label for spec in self.available_specs],
            state="readonly",
            width=64,
        )
        self.model_combo.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(4, 12)
        )
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_changed)

        ttk.Label(
            sidebar, text="이미지 목록", font=(self.ui_font_family, 14, "bold")
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.image_list = tk.Listbox(
            sidebar, width=34, activestyle="dotbox", exportselection=False
        )
        self.image_list.grid(row=3, column=0, sticky="nsew")
        self.image_list.bind("<<ListboxSelect>>", self._on_select)

        scrollbar = ttk.Scrollbar(
            sidebar, orient="vertical", command=self.image_list.yview
        )
        scrollbar.grid(row=3, column=1, sticky="ns")
        self.image_list.configure(yscrollcommand=scrollbar.set)

        button_frame = ttk.Frame(sidebar)
        button_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        button_frame.columnconfigure((0, 1), weight=1)

        self.selected_button = ttk.Button(
            button_frame, text="선택 이미지 분석", command=self.analyze_selected
        )
        self.selected_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.all_button = ttk.Button(
            button_frame, text="전체 다시 분석", command=self.analyze_all
        )
        self.all_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.webcam_button = ttk.Button(
            button_frame, text="웹캠 실시간 탐지", command=self.open_webcam
        )
        self.webcam_button.grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

        self.manual_button = ttk.Button(
            button_frame, text="OMX 수동 관절 제어", command=self.open_manual_control
        )
        self.manual_button.grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

        self.camera_selector = CameraSelector(sidebar, busy=self._camera_in_use)
        self.camera_selector.grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0)
        )

    def _build_compare_panel(self) -> None:
        content = ttk.Frame(self, padding=(0, 10, 10, 10))
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure((0, 2), weight=1, uniform="preview")
        content.columnconfigure(1, weight=0)
        content.rowconfigure(1, weight=1)

        ttk.Label(
            content, text="변환 전", font=(self.ui_font_family, 14, "bold")
        ).grid(row=0, column=0, pady=(0, 8))
        ttk.Label(
            content, text="변환 후", font=(self.ui_font_family, 14, "bold")
        ).grid(row=0, column=2, pady=(0, 8))

        self.original_label = ttk.Label(
            content, text="이미지를 선택하세요", anchor="center", relief="solid"
        )
        self.original_label.grid(row=1, column=0, sticky="nsew", padx=(0, 5))

        reanalyze_panel = ttk.Frame(content)
        reanalyze_panel.grid(row=1, column=1, padx=10)

        self.compare_reanalyze_button = ttk.Button(
            reanalyze_panel,
            text="이 이미지만\n다시 분석 →",
            command=self.analyze_selected,
            width=16,
        )
        self.compare_reanalyze_button.pack()

        self.selected_progress = ttk.Progressbar(
            reanalyze_panel, mode="determinate", maximum=100, length=135
        )
        self.selected_progress.pack(fill="x", pady=(12, 4))

        self.selected_progress_text = tk.StringVar(value="대기 중")
        ttk.Label(
            reanalyze_panel, textvariable=self.selected_progress_text, anchor="center"
        ).pack(fill="x")

        self.result_label = ttk.Label(
            content, text="분석 결과가 없습니다", anchor="center", relief="solid"
        )
        self.result_label.grid(row=1, column=2, sticky="nsew", padx=(5, 0))

        self.status = tk.StringVar(value="준비")
        ttk.Label(content, textvariable=self.status, anchor="w").grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0)
        )
        self.progress = ttk.Progressbar(content, mode="determinate")
        self.progress.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))

    def _build_console(self) -> None:
        self.console = ConsolePanel(self, self._console_redirector.queue)
        self.console.grid(
            row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10)
        )

    # ------------------------------------------------------------------ 콘솔/종료

    def _drain_console(self) -> None:
        self.console.drain()
        if self.winfo_exists():
            self.after(CONSOLE_POLL_MS, self._drain_console)

    def _on_close(self) -> None:
        if self._manual_process is not None and self._manual_process.poll() is None:
            messagebox.showinfo(
                "수동 제어 실행 중",
                "수동 관절 제어 창을 먼저 닫아 주세요.",
                parent=self,
            )
            return
        if self.webcam_window is not None and self.webcam_window.winfo_exists():
            self.webcam_window.close()
        self._console_redirector.restore()
        self.destroy()

    # ------------------------------------------------------------------ 이미지 목록

    def refresh_images(self) -> None:
        selected = self._selected_path()
        selected_name = selected.name if selected else None
        if self.input_dir.is_dir():
            self.image_paths = sorted(
                path
                for path in self.input_dir.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            )
        else:
            self.image_paths = []

        self.image_list.delete(0, tk.END)
        selected_index = 0
        for index, image_path in enumerate(self.image_paths):
            marker = "✓" if self._result_path(image_path).exists() else "○"
            self.image_list.insert(tk.END, f"{marker}  {image_path.name}")
            if image_path.name == selected_name:
                selected_index = index

        if self.image_paths:
            self.image_list.selection_set(selected_index)
            self.image_list.see(selected_index)
            self.show_selected()
        else:
            self.status.set(f"입력 이미지가 없습니다: {self.input_dir}")

    def _selected_path(self) -> Path | None:
        selection = self.image_list.curselection()
        if not selection or selection[0] >= len(self.image_paths):
            return None
        return self.image_paths[selection[0]]

    def _result_path(self, image_path: Path, model_path: Path | None = None) -> Path:
        selected_model = model_path or self.model_path
        return self.output_dir / selected_model.stem / f"det_{image_path.name}"

    def _on_select(self, _event: tk.Event) -> None:
        self.show_selected()

    def show_selected(self) -> None:
        image_path = self._selected_path()
        if image_path is None:
            return

        self.original_photo = self._load_preview(image_path)
        if self.original_photo is None:
            self.original_label.configure(image="", text="미리보기를 표시할 수 없습니다.")
        else:
            self.original_label.configure(image=self.original_photo, text="")

        result_path = self._result_path(image_path)
        if result_path.exists():
            self.result_photo = self._load_preview(result_path)
            if self.result_photo is None:
                self.result_label.configure(image="", text="미리보기를 표시할 수 없습니다.")
            else:
                self.result_label.configure(image=self.result_photo, text="")
        else:
            self.result_photo = None
            self.result_label.configure(image="", text="아직 분석되지 않았습니다.")

        self.status.set(image_path.name)

    @staticmethod
    def _load_preview(path: Path) -> ImageTk.PhotoImage | None:
        try:
            with Image.open(path) as source:
                image = (ImageOps.exif_transpose(source) or source).convert("RGB")
                image.thumbnail(PREVIEW_SIZE, Image.Resampling.LANCZOS)
                return ImageTk.PhotoImage(image)
        except Exception:
            traceback.print_exc()
            return None

    # ------------------------------------------------------------------ 모델 준비

    @property
    def model_path(self) -> Path:
        return MODELS_DIR / SPECS_BY_LABEL[self.model_choice.get()].filename

    def _on_model_changed(self, _event: tk.Event) -> None:
        self.model = None
        self.loaded_model_path = None
        self.selected_progress.configure(value=0)
        self.selected_progress_text.set("대기 중")
        self.progress.configure(value=0)
        self.refresh_images()
        self.status.set(f"모델 전환 완료: {self.model_path.name}")

    def _prepare_models(self) -> None:
        missing_models = missing_model_paths()
        if not missing_models:
            self._start_initial_analysis()
            return

        self.progress.configure(maximum=len(missing_models), value=0)
        self.status.set(f"누락 모델 {len(missing_models)}개 다운로드 준비 중...")
        print(
            "[model download start] "
            + ", ".join(model_path.name for model_path in missing_models)
        )
        self._start_worker(self._download_models_worker, missing_models)

    def _download_models_worker(self, model_paths: list[Path]) -> None:
        try:
            for index, model_path in enumerate(model_paths, start=1):
                self.after(
                    0,
                    self.status.set,
                    f"[{index}/{len(model_paths)}] 다운로드 중: {model_path.name}",
                )
                download_model(model_path)
                print(f"[{index}/{len(model_paths)}] model ready: {model_path.name}")
                self.after(
                    0,
                    self._model_download_progress,
                    index,
                    len(model_paths),
                    model_path.name,
                )
            self.after(0, self._model_download_finished, len(model_paths))
        except Exception as error:
            traceback.print_exc()
            self.after(0, self._model_download_failed, str(error))

    def _model_download_progress(
        self, current: int, total: int, model_name: str
    ) -> None:
        self.progress.configure(value=current)
        self.status.set(f"[{current}/{total}] 모델 준비 완료: {model_name}")

    def _model_download_finished(self, count: int) -> None:
        self._finish_processing()
        self.progress.configure(value=count)
        self.status.set(f"모델 다운로드 완료: {count}개")
        print(f"[model download complete] models={count}")
        self.after(100, self._start_initial_analysis)

    def _model_download_failed(self, error: str) -> None:
        self._finish_processing()
        self.progress.configure(value=0)
        self.status.set("모델 다운로드 중 오류가 발생했습니다.")
        messagebox.showerror(
            "모델 다운로드 오류",
            "인터넷 연결을 확인한 뒤 프로그램을 다시 실행해 주세요.\n\n" f"{error}",
        )

    # ------------------------------------------------------------------ 분석 실행

    def _start_initial_analysis(self) -> None:
        if not self.image_paths or not self._ensure_model_available():
            return

        existing = [
            path for path in self.image_paths if self._result_path(path).exists()
        ]
        if existing:
            skip_existing = messagebox.askyesno(
                "기존 결과 확인",
                f"{self.model_path.name} 모델로 이미 분석한 이미지는 생략할까요?\n\n"
                "Yes: 기존 결과 유지\nNo: 모든 이미지 다시 분석",
            )
            targets = (
                [
                    path
                    for path in self.image_paths
                    if not self._result_path(path).exists()
                ]
                if skip_existing
                else self.image_paths
            )
        else:
            targets = self.image_paths

        if targets:
            self._run_analysis(targets)
        else:
            self.status.set("모든 이미지가 이미 분석된 상태입니다.")

    def analyze_selected(self) -> None:
        image_path = self._selected_path()
        if image_path:
            self.selected_progress.configure(value=0)
            self.selected_progress_text.set("0% · 진행 중")
            self._run_analysis([image_path])

    def analyze_all(self) -> None:
        self._run_analysis(self.image_paths)

    # ------------------------------------------------------------------ 장비 도구

    def open_webcam(self) -> None:
        if self.webcam_window is not None and self.webcam_window.winfo_exists():
            self.webcam_window.lift()
            self.webcam_window.focus_force()
            return
        if self._camera_is_scanning():
            # 검색은 장치를 직접 열어 보므로, 끝나기 전에 열면 서로 점유해 실패한다.
            messagebox.showinfo("카메라 검색 중", SCANNING_MESSAGE, parent=self)
            return
        if not self._ensure_model_available():
            return
        camera_index = (
            self.camera_selector.selected_index()
            if self.camera_selector is not None
            else 0
        )
        # 배치 분석과 스레드 충돌이 없도록 웹캠 창은 자체 모델 인스턴스를 로드한다.
        self.webcam_window = WebcamWindow(
            self,
            model_path=self.model_path,
            input_dir=self.input_dir,
            on_snapshot=lambda _path: self.refresh_images(),
            camera_index=camera_index,
        )
        self.status.set(
            f"웹캠 실시간 탐지 시작: {self.model_path.name} · 카메라 {camera_index}번"
        )

    def open_manual_control(self) -> None:
        if self._manual_process is not None and self._manual_process.poll() is None:
            messagebox.showinfo(
                "수동 제어 실행 중",
                "이미 열려 있는 수동 관절 제어 창을 사용하세요.",
                parent=self,
            )
            return
        loading_port, _sorting_port = assign_omx_ports(list_serial_ports())
        port = loading_port or fallback_omx_port()
        # 같은 폴더의 파일이므로 __file__ 기준으로 찾는다.
        manual_control = Path(__file__).with_name("omx_manual_control.py")
        try:
            self._manual_process = subprocess.Popen(
                [sys.executable, str(manual_control), "--port", port],
                cwd=PROJECT_DIR,
            )
        except Exception as error:
            messagebox.showerror("OMX 실행 오류", str(error), parent=self)
            return
        self.status.set(f"수동 관절 제어 실행 중 · {port}")
        self.manual_button.configure(state="disabled")
        self.after(250, self._poll_manual_process)

    def _poll_manual_process(self) -> None:
        process = self._manual_process
        if process is not None and process.poll() is None:
            self.after(250, self._poll_manual_process)
            return
        self._manual_process = None
        if self.winfo_exists():
            self.manual_button.configure(state="normal")
            self.status.set("수동 관절 제어 종료됨")

    def _webcam_is_open(self) -> bool:
        return self.webcam_window is not None and bool(
            self.webcam_window.winfo_exists()
        )

    def _camera_is_scanning(self) -> bool:
        return (
            self.camera_selector is not None and self.camera_selector.is_scanning()
        )

    def _camera_in_use(self) -> bool:
        return self._webcam_is_open()

    def _ensure_model_available(self) -> bool:
        if self.model_path.exists():
            return True
        messagebox.showerror("모델 오류", f"모델 파일이 없습니다:\n{self.model_path}")
        return False

    # ------------------------------------------------------------------ 워커

    def _run_analysis(self, targets: list[Path]) -> None:
        if self.processing or not targets or not self._ensure_model_available():
            return

        active_model_path = self.model_path
        self._result_path(targets[0], active_model_path).parent.mkdir(
            parents=True, exist_ok=True
        )
        self.progress.configure(maximum=len(targets), value=0)
        self.status.set(f"{len(targets)}개 이미지 분석 준비 중...")
        self._start_worker(self._analyze_worker, list(targets), active_model_path)

    def _start_worker(self, target, *args) -> None:
        self.processing = True
        self._set_buttons_enabled(False)
        threading.Thread(target=target, args=args, daemon=True).start()

    def _analyze_worker(self, targets: list[Path], active_model_path: Path) -> None:
        try:
            if self.model is None or self.loaded_model_path != active_model_path:
                self.after(
                    0, self.status.set, f"모델 로딩 중: {active_model_path.name}"
                )
                # processing 플래그가 워커를 한 번에 하나로 제한하므로,
                # 메인 스레드는 processing 중 self.model을 바꾸지 않는다.
                self.model = YOLO(str(active_model_path))
                self.loaded_model_path = active_model_path

            print(
                f"[analysis start] model={active_model_path.name}, "
                f"images={len(targets)}"
            )
            failures = run_analysis(
                self.model,
                targets,
                lambda image_path: self._result_path(image_path, active_model_path),
                on_progress=lambda index, total, image_path, ok: self.after(
                    0, self._analysis_progress, index, total, image_path, ok
                ),
            )
            print(f"[analysis complete] images={len(targets) - len(failures)}")
            if failures and len(failures) == len(targets):
                self.after(
                    0,
                    self._analysis_failed,
                    "모든 이미지 분석에 실패했습니다:\n" + "\n".join(failures),
                )
            else:
                self.after(
                    0,
                    self._analysis_finished,
                    len(targets) - len(failures),
                    failures,
                )
        except Exception as error:
            traceback.print_exc()
            self.after(0, self._analysis_failed, str(error))

    def _analysis_progress(
        self, current: int, total: int, image_path: Path, succeeded: bool = True
    ) -> None:
        percentage = round(current / total * 100)
        self.progress.configure(value=current)
        self.selected_progress.configure(value=percentage)
        self.selected_progress_text.set(f"{percentage}% · 결과 저장 완료")
        outcome = "완료" if succeeded else "실패"
        self.status.set(f"[{current}/{total}] {outcome}: {image_path.name}")
        self._update_image_marker(image_path)
        if image_path == self._selected_path():
            self.show_selected()

    def _update_image_marker(self, image_path: Path) -> None:
        try:
            index = self.image_paths.index(image_path)
        except ValueError:
            return
        marker = "✓" if self._result_path(image_path).exists() else "○"
        was_selected = index in self.image_list.curselection()
        self.image_list.delete(index)
        self.image_list.insert(index, f"{marker}  {image_path.name}")
        if was_selected:
            self.image_list.selection_set(index)

    def _analysis_finished(self, count: int, failures: list[str]) -> None:
        self._finish_processing()
        self.refresh_images()
        self.selected_progress.configure(value=100)
        self.selected_progress_text.set("100% · 분석 완료")
        if failures:
            self.status.set(f"분석 완료: {count}개 성공, {len(failures)}개 실패")
            messagebox.showwarning(
                "일부 이미지 분석 실패",
                f"{len(failures)}개 이미지를 분석하지 못했습니다:\n"
                + "\n".join(failures),
            )
        else:
            self.status.set(f"분석 완료: {count}개")

    def _analysis_failed(self, error: str) -> None:
        self._finish_processing()
        self.selected_progress.configure(value=0)
        self.selected_progress_text.set("오류 발생")
        self.status.set("분석 중 오류가 발생했습니다.")
        messagebox.showerror("분석 오류", error)

    def _finish_processing(self) -> None:
        self.processing = False
        self._set_buttons_enabled(True)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        self.selected_button.configure(state=state)
        self.all_button.configure(state=state)
        self.compare_reanalyze_button.configure(state=state)
        self.model_combo.configure(state="readonly" if enabled else "disabled")


def main() -> None:
    app = DevConsoleApp()
    app.mainloop()


if __name__ == "__main__":
    main()
