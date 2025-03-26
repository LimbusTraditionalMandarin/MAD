# This file is part of MAD project which is released under GNU GPL v3.0.
# Copyright (c) 2025- Limbus Traditional Mandarin

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from os import popen
from pathlib import Path
from platform import system as os_name
from re import match as rematch
from shlex import shlex
from shutil import rmtree
from typing import Any, Literal
from zipfile import ZipFile

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMainWindow
from requests import get as rqget


def require_game_stoping(method: Callable):
    """Requires game to be closed."""

    @wraps(method)
    def wrapper(self, *args, **kwargs) -> None | Any:
        if "LimbusCompany.exe" in popen("tasklist").read():
            self._add_log("偵測到遊戲正在運行,請先關閉遊戲再進行操作!")
            return None
        return method(self, *args, **kwargs)

    return wrapper


@dataclass
class ButtonConfig:
    geometry: QtCore.QRect
    png_prefix: str
    callback: Callable
    text: str = ""
    icon_size: QtCore.QSize | None = None
    btn_type: Literal["text", "icon"] = field(init=False)

    def __post_init__(self) -> None:
        self.btn_type = "icon" if not self.text else "text"

        if self.icon_size is None:
            self.icon_size = QtCore.QSize(35, 35) if not self.text else QtCore.QSize(250, 110)


@dataclass
class Supporter:
    name: str
    price: float
    currency: str


class UIComponentFactory:
    @staticmethod
    def create_button(
        parent: QObject,
        config: ButtonConfig,
        assets_dir: Path,
    ) -> QtWidgets.QPushButton:
        enter_img = assets_dir / f"{config.png_prefix}_T.png"
        leave_img = assets_dir / f"{config.png_prefix}_F.png"

        if config.btn_type == "text":
            button = TextButton(enter_img, leave_img, config.text, parent)
        else:
            button = IconButton(enter_img, leave_img, parent)

        button.setGeometry(config.geometry)
        button.setIconSize(config.icon_size)
        return button

    @staticmethod
    def create_image_label(
        parent: QObject,
        geometry: QtCore.QRect,
        pixmap: Path,
    ) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(parent)
        label.setGeometry(geometry)
        if pixmap.exists():
            label.setPixmap(QtGui.QPixmap(str(pixmap)))
        label.setScaledContents(True)

        label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return label


class TextButton(QtWidgets.QPushButton):
    def __init__(self, enter_img: Path, leave_img: Path, text: str, parent: QObject = None) -> None:
        super().__init__(parent)
        self.enter_img = enter_img
        self.leave_img = leave_img
        self._setup_ui(text)

    def _setup_ui(self, text: str) -> None:
        self.setIcon(QtGui.QIcon(str(self.leave_img)))
        self.setStyleSheet("background: transparent; border: none;")

        self.label = QtWidgets.QLabel(self)
        self.label.setText(text)
        self.label.setFont(QtGui.QFont("Microsoft JhengHei UI", 25, QtGui.QFont.Bold))
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.label.setGeometry(20, 0, 250, 110)
        self.label.setStyleSheet("font-size: 35px; color: black;")

    def enterEvent(self, event) -> None:
        self.setIcon(QtGui.QIcon(str(self.enter_img)))
        self.label.setStyleSheet("font-size: 35px; color: rgb(236,204,163);")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setIcon(QtGui.QIcon(str(self.leave_img)))
        self.label.setStyleSheet("font-size: 35px; color: black;")
        super().leaveEvent(event)


class IconButton(QtWidgets.QPushButton):
    def __init__(self, enter_img: Path, leave_img: Path, parent: QObject = None) -> None:
        super().__init__(parent)
        self.enter_img = enter_img
        self.leave_img = leave_img
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setIcon(QtGui.QIcon(str(self.leave_img)))
        self.setStyleSheet("background: transparent; border: none;")

    def enterEvent(self, event) -> None:
        self.setIcon(QtGui.QIcon(str(self.enter_img)))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setIcon(QtGui.QIcon(str(self.leave_img)))
        super().leaveEvent(event)


class WorkerSignals(QObject):
    progress = Signal(int)
    finished = Signal()


class DownloadWorker(QRunnable):
    def __init__(self, url: str, dest: Path) -> None:
        super().__init__()
        self.url = url
        self.dest = dest
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            with rqget(self.url, stream=True) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0

                with self.dest.open("wb") as f:
                    for chunk in response.iter_content(8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                self.signals.progress.emit(int((downloaded * 100) / total_size))
            self.signals.finished.emit()
        except Exception as e:
            print(f"Download error: {e}")


class ExtractWorker(QRunnable):
    def __init__(self, archive: Path, output: Path) -> None:
        super().__init__()
        self.archive = archive
        self.output = output
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            with ZipFile(self.archive, "r") as zip_ref:
                total = len(zip_ref.infolist())
                for i, file in enumerate(zip_ref.infolist()):
                    zip_ref.extract(file, self.output)
                    self.signals.progress.emit(int(((i + 1) * 100) / total))
            self.archive.unlink()
            self.signals.finished.emit()
        except Exception as e:
            print(f"Extract error: {e}")


class TaskController(QObject):
    progress = Signal(int)
    finished = Signal()

    def __init__(self, tasks: list) -> None:
        super().__init__()
        self.tasks = tasks
        self.current = 0

    def start(self) -> None:
        self._execute_next()

    def _execute_next(self) -> None:
        if self.current >= len(self.tasks):
            self.finished.emit()
            return

        task = self.tasks[self.current]
        if task["type"] == "download":
            worker = DownloadWorker(task["url"], task["destination"])
        else:
            worker = ExtractWorker(task["archive"], task["output"])

        worker.signals.progress.connect(self.progress.emit)
        worker.signals.finished.connect(self._on_worker_finished)
        QThreadPool.globalInstance().start(worker)

    def _on_worker_finished(self):
        self.current += 1
        self._execute_next()


class HistoryManager:
    def __init__(self, history_file: Path) -> None:
        self.file = history_file
        self.data = self._load()

    def _load(self) -> dict:
        if self.file.exists():
            with self.file.open("r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save(self) -> None:
        with self.file.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)


class SupporterWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("抖內視窗")
        self.resize(300, 200)

        main_layout = QtWidgets.QGridLayout()

        supporters = [
            ("Xiink", "100", "我愛巴士 我愛巴士"),
            ("Xiink_JP", "10", "巴士愛我 巴士愛我"),
        ]

        for i, (name, coffee, note) in enumerate(supporters):
            support_layout = QtWidgets.QVBoxLayout()  # 每次循环都创建新的 QVBoxLayout
            support_layout.addWidget(QtWidgets.QLabel(f"{name}"))
            support_layout.addWidget(QtWidgets.QLabel(f"{coffee}"))
            support_layout.addWidget(QtWidgets.QLabel(f"{note}"))

            support_widget = QtWidgets.QWidget()
            support_widget.setLayout(support_layout)  # 绑定新创建的 layout

            main_layout.addWidget(support_widget, 0, i)  # 横向排列 (列递增)

        self.setLayout(main_layout)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        # Method that will not be disabled
        self.METHOD_WHITELIST = (self.showMinimized, self._get_supporter_list)

        self.game_path = self._find_game_path()
        self.history = HistoryManager(self.game_path / "AutoLLC.history")
        self.supporter_window = None
        self._setup_ui()
        self._init_resources()

    def _setup_ui(self) -> None:
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setFixedSize(800, 600)

        base = Path.cwd() / "assets"
        factory = UIComponentFactory()

        # Basic framework
        self.bg_label = factory.create_image_label(
            self,
            QtCore.QRect(0, 0, 790, 600),
            base / "BasePlate.png",
        )
        self.outer_frame = factory.create_image_label(
            self,
            QtCore.QRect(0, 0, 790, 600),
            base / "OuterFrame1.png",
        )
        self.log_frame = factory.create_image_label(
            self,
            QtCore.QRect(280, 50, 480, 460),
            base / "OuterFrame2.png",
        )

        # Progress bar component
        self.progress_bar_bg = factory.create_image_label(
            self,
            QtCore.QRect(55, 520, 680, 50),
            base / "BasePlateBar.png",
        )
        self.progress_bar_frame = factory.create_image_label(
            self,
            QtCore.QRect(30, 520, 730, 51),
            base / "OuterFrameBar.png",
        )

        # Function buttons
        btn_configs = [
            ButtonConfig(
                QtCore.QRect(12, 70, 250, 110),
                "FnButton",
                self.normal_install,
                text="自動更新",
            ),
            ButtonConfig(
                QtCore.QRect(12, 150, 250, 110),
                "FnButton",
                self.re_install,
                text="重新安裝",
            ),
            ButtonConfig(
                QtCore.QRect(12, 230, 250, 110),
                "FnButton",
                self.remove_module,
                text="移除漢化",
            ),
            ButtonConfig(
                QtCore.QRect(12, 420, 250, 110),
                "FnButton",
                self.close,
                text="離開工具",
            ),
            ButtonConfig(
                QtCore.QRect(650, -5, 60, 60),
                "MinButton",
                self.showMinimized,
            ),
            ButtonConfig(
                QtCore.QRect(700, -5, 60, 60),
                "CloseButton",
                self.close,
            ),
            ButtonConfig(
                QtCore.QRect(10, 7, 55, 55),
                "Donate",
                self._get_supporter_list,
                icon_size=QtCore.QSize(55, 55),
            ),
        ]

        self.buttons: list[QtWidgets.QPushButton] = []
        for config in btn_configs:
            btn = factory.create_button(self, config, base)
            btn.clicked.connect(config.callback)
            if config.callback in self.METHOD_WHITELIST:
                btn.setProperty("exclude_disable", True)
            self.buttons.append(btn)

        # Progress bar settings
        self.progress_bar = QtWidgets.QProgressBar(self)
        self.progress_bar.setGeometry(55, 520, 680, 46)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: transparent;
                border: 0px solid #bbb;
                border-radius: 5px;
                text-align: center;
                font: bold 30px "Microsoft JhengHei UI";
                color: rgb(236,204,163);
            }
            QProgressBar::chunk {
                background-color: rgb(1,170,57);
                width: 20px;
                margin: 0px;
            }
        """)
        self.progress_bar.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._update_progress(100)

        # Log list
        self.log_list = QtWidgets.QListWidget(self)
        self.log_list.setGeometry(300, 110, 440, 380)
        self.log_list.setStyleSheet("""
            background: black; color: white; border: none;
            font: bold 14pt 'Microsoft JhengHei UI';
        """)

        # Title text
        self.title_label = QtWidgets.QLabel(self)
        self.title_label.setText("Limbus Company繁中漢化工具")
        self.title_label.setGeometry(70, 5, 550, 35)
        self.title_label.setStyleSheet("""
            font: bold 25px 'Microsoft JhengHei UI'; color: black;
        """)

        # Operating instructions
        self.info_label = QtWidgets.QLabel(self)
        self.info_label.setText(
            "正常更新請點擊自動更新\n重大更新請點擊重新安裝\n運行完後將自動啟動遊戲",
        )
        self.info_label.setGeometry(15, 330, 250, 100)
        self.info_label.setStyleSheet("""
            font: bold 22px 'Microsoft JhengHei UI';
            color: rgb(115,76,41);
        """)
        self.info_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Layer order adjustment
        self.bg_label.lower()
        self.outer_frame.raise_()
        self.log_frame.raise_()
        self.progress_bar_bg.raise_()
        self.progress_bar.raise_()
        self.progress_bar_frame.raise_()

        # Make sure core components are at the top
        self.log_list.raise_()
        self.title_label.raise_()
        self.info_label.raise_()
        for btn in self.buttons:
            btn.raise_()

    @classmethod
    def _find_game_path(cls) -> Path:
        if os_name().lower() != "windows":
            raise NotImplementedError("This App only supports Windows systems")

        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam_path = Path(winreg.QueryValueEx(key, "SteamPath")[0])

            libs = json.loads(
                cls._parse_vdf((steam_path / "steamapps/libraryfolders.vdf").read_text()),
            )
            for lib in libs["libraryfolders"].values():
                if (
                    path := Path(lib["path"]) / "steamapps/common/Limbus Company/LimbusCompany.exe"
                ).exists():
                    return path.parent
            raise FileNotFoundError("Game installation path not found")
        except Exception as e:
            raise RuntimeError(f"Path lookup failed: {e}") from e

    @staticmethod
    def _parse_vdf(content: str) -> str:
        def _istr(ident: int, string: str) -> str:
            return (ident * "  ") + string

        jbuf = "{\n"
        lex = shlex(content)
        indent = 1
        while True:
            tok = lex.get_token()
            if not tok:
                return jbuf + "}\n"
            if tok == "}":
                indent -= 1
                jbuf += _istr(indent, "}")
                ntok = lex.get_token()
                lex.push_token(ntok)
                if ntok and ntok != "}":
                    jbuf += ","
                jbuf += "\n"
            else:
                ntok = lex.get_token()
                if ntok == "{":
                    jbuf += _istr(indent, tok + ": {\n")
                    indent += 1
                else:
                    jbuf += _istr(indent, tok + ": " + ntok)
                    ntok = lex.get_token()
                    lex.push_token(ntok)
                    if ntok != "}":
                        jbuf += ","
                    jbuf += "\n"

    def _init_resources(self):
        self.api_mapping = {
            "BepInEx/BepInEx": r"https.*BepInEx-Unity.IL2CPP-win-x64-6.*.zip",
            "LimbusTraditionalMandarin/font": r"https.*LTM_font.*.zip",
            "LimbusTraditionalMandarin/storyline": r"https.*LTM_.*.zip",
        }

    def _update_progress(self, value: int) -> None:
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"{value}/100")

    def _add_log(self, message: str) -> None:
        self.log_list.addItem(QtWidgets.QListWidgetItem(message))

    def _clean_installation(self) -> bool:
        if not self.history.data:
            self._add_log("未找到漢化模組")
            return False

        targets = [
            "BepInEx",
            "dotnet",
            "AutoLLC.history",
            "doorstop_config.ini",
            "winhttp.dll",
            ".doorstop_version",
            "changelog.txt",
            "Latest(框架日志).log",
            "Player(遊戲日志).log",
        ]
        for item in targets:
            path = self.game_path / item
            if path.is_dir():
                rmtree(path)
            elif path.exists():
                path.unlink()
            self._add_log(f"已移除: {path}")
        self._add_log("漢化模組已移除")
        self.history.data = {}

        return True

    def _start_installation(self, clean: bool = False) -> None:
        for btn in self.buttons:
            if not btn.property("exclude_disable"):
                btn.setEnabled(False)

        if clean and self._clean_installation():
            self._add_log("舊模組已移除")

        self._add_log(f"模組安裝位置: {self.game_path}")
        tasks = []
        for name, pattern in self.api_mapping.items():
            if url := self._get_download_url(name, pattern):
                if name in self.history.data and self.history.data[name] == url:
                    self._add_log(f"模組 {name} 已是最新版本")
                    continue

                self._add_log(f"更新模組 {name}: {url}")
                dest = Path(tempfile.gettempdir()) / f"limbus_{name.replace('/', '_')}.zip"
                tasks.extend(
                    [
                        {"type": "download", "url": url, "destination": dest},
                        {"type": "extract", "archive": dest, "output": self.game_path},
                    ],
                )
                self.history.data[name] = url
            # elif url is None:

        if tasks:
            self.controller = TaskController(tasks)
            self.controller.progress.connect(self._update_progress)
            self.controller.finished.connect(self._on_install_finished)
            self.controller.start()
        else:
            self._add_log("沒有需要下載的任務")
            self._launch_game()

    def _get_download_url(self, api_part: str, pattern: str) -> str | None:
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            raise TimeoutError

            response = rqget(
                f"https://api.github.com/repos/{api_part}/releases",
                headers=headers,
            )
            response.raise_for_status()
            for asset in response.json()[0]["assets"]:
                url = asset["browser_download_url"]
                if rematch(pattern, url):
                    return url
        except Exception as e:
            self._add_log(f"獲取下載連結失敗: {e!s}")
        return None

    def _get_supporter_list(self) -> None:
        if not self.supporter_window or not self.supporter_window.isVisible():
            self.supporter_window = SupporterWindow()
            self.supporter_window.show()

        with open("TOKEN") as file:
            api_key = file.read()

        self.supporter_list: list[Supporter] = []
        headers = {"Authorization": f"Bearer {api_key}"}
        current_page = 1

        while True:
            url = f"https://developers.buymeacoffee.com/api/v1/supporters?page={current_page}"

            response = rqget(url, headers=headers)

            if response.status_code != 200:
                print(f"Failed:{response.status_code}")
                break

            data = response.json()

            if "error" in data:
                self._add_log(data["error"])
                break

            for supporter in data["data"]:
                payer_name = supporter.get("payer_name", "Anonymous").strip() or "Anonymous"
                coffee_price = supporter["support_coffee_price"].rstrip("0").rstrip(".")
                currency = supporter["support_currency"]
                self.supporter_list.append(Supporter(payer_name, coffee_price, currency))
                print(f"{payer_name} donated: {coffee_price} {currency}")

            if data.get("next_page_url"):
                current_page += 1
            else:
                break

        while True:
            url = f"https://developers.buymeacoffee.com/api/v1/subscriptions?page={current_page}"

            response = rqget(url, headers=headers)

            if response.status_code != 200:
                print(f"Failed:{response.status_code}")
                break

            data = response.json()

            if "error" in data:
                self._add_log(data["error"])
                break

            for supporter in data["data"]:
                payer_name = supporter.get("payer_name", "Anonymous").strip() or "Anonymous"
                coffee_price = supporter["subscription_coffee_price"].rstrip("0").rstrip(".")
                currency = supporter["subscription_currency"]
                self.supporter_list.append(Supporter(payer_name, coffee_price, currency))
                print(f"{payer_name} donated: {coffee_price} {currency}")

            if data.get("next_page_url"):
                current_page += 1
            else:
                break

        try:
            for supporter in self.supporter_list:
                self._add_log(f"{supporter.name} donated {supporter.price} {supporter.currency}")

        except Exception as e:
            self._add_log(f"獲取抖內清單失敗: {e}")

    def _on_install_finished(self) -> None:
        self.history.save()
        self._add_log("模組安裝完畢!")
        self._launch_game()

    def _launch_game(self) -> None:
        self._add_log("即將為您啟動遊戲!")
        if not any("steam" in line.lower() for line in popen("tasklist").readlines()):
            subprocess.run(["steam", "://rungameid/1973530"], check=False)
        else:
            subprocess.run([str(self.game_path / "LimbusCompany.exe")], check=False)
        for btn in self.buttons:
            btn.setEnabled(True)

        self._add_log("啟動器將於2秒後關閉!")
        QtCore.QTimer.singleShot(2000, self.close)

    @require_game_stoping
    def normal_install(self) -> None:
        self._start_installation()

    @require_game_stoping
    def re_install(self) -> None:
        self._start_installation(clean=True)

    @require_game_stoping
    def remove_module(self) -> None:
        self._clean_installation()

    def closeEvent(self, event) -> None:
        QThreadPool.globalInstance().waitForDone()
        super().closeEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.drag_start_position = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if hasattr(self, "drag_start_position") and (
            event.buttons() & QtCore.Qt.MouseButton.LeftButton
        ):
            current_position = event.globalPosition().toPoint()
            delta = current_position - self.drag_start_position
            self.move(self.pos() + delta)
            self.drag_start_position = current_position

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if hasattr(self, "drag_start_position"):
            del self.drag_start_position


if __name__ == "__main__":
    app = QApplication(sys.argv)

    instance_key = "LimbusCompanyInstaller"
    socket = QLocalSocket()
    socket.connectToServer(instance_key)
    if socket.waitForConnected(100):
        # Execution already exists, exit directly
        sys.exit(0)

    server = QLocalServer()
    server.listen(instance_key)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
