# This file is part of MAD project which is released under GNU GPL v3.0.
# Copyright (c) 2025- Limbus Traditional Mandarin

import json
import string
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from os import popen
from pathlib import Path
from re import match as rematch
from shlex import shlex
from shutil import rmtree
from typing import Any, Literal
from zipfile import ZipFile

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMainWindow
from requests import JSONDecodeError, RequestException, Session

from TOKEN import BUY_ME_A_COFFEE_TOKEN


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

    @staticmethod
    def truncate(s: str) -> str:
        cost = lambda ch: 1 if ch in string.ascii_letters else 0.75 if ch.isdigit() else 1.25
        total, cum = 0, []
        for ch in s:
            total += cost(ch)
            cum.append(total)
        return s if total <= 15 else f"{s[: next(i for i, v in enumerate(cum) if v > 14.25)]}…"

    @classmethod
    def create_supporter_data(
        cls,
        supporter: Supporter,
        name_pixmap: Path,
    ) -> QtWidgets.QVBoxLayout:
        support_layout = QtWidgets.QVBoxLayout()
        support_layout.setSpacing(0)
        support_layout.setContentsMargins(0, 0, 0, 0)

        label_name = ImageLabel(
            f"{name_pixmap}",
            f"{cls.truncate(supporter.name)}\n{supporter.price:.2f} {supporter.currency}",
        )
        support_layout.addWidget(label_name)
        return support_layout


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


class ImageLabel(QtWidgets.QLabel):
    def __init__(self, image_path, text, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.text = text
        self.setFixedSize(220, 100)
        self.setFont(QtGui.QFont("Microsoft JhengHei UI", 13, QtGui.QFont.Bold))
        self.setStyleSheet("border: 0px solid white; padding: 0px;")

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)

        if Path(self.image_path).exists():
            pixmap = QtGui.QPixmap(self.image_path)
            pixmap = pixmap.scaled(
                self.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, self.width(), self.height(), pixmap)

        painter.setPen(QtGui.QColor("White"))
        painter.setFont(self.font())
        painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, self.text)

        painter.end()


class WorkerSignals(QObject):
    progress = Signal(int)
    finished = Signal()


class DownloadWorker(QRunnable):
    def __init__(self, url: str, dest: Path) -> None:
        super().__init__()
        self.url = url
        self.dest = dest
        self.signals = WorkerSignals()
        self.session = Session()

    def run(self) -> None:
        try:
            with self.session.get(self.url, stream=True) as response:
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
        except Exception as e:
            print(f"Download error: {e}")
        finally:
            self.session.close()
            self.signals.finished.emit()


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
        except Exception as e:
            print(f"Extract error: {e}")
        finally:
            self.archive.unlink()
            self.signals.finished.emit()


class GetSupporterList(QRunnable):
    def __init__(self, headers: dict, supporter_list: list[Supporter]) -> None:
        super().__init__()
        self.headers = headers
        self.signals = WorkerSignals()
        self.session = Session()
        self.session.headers.update(headers)

        # Share memory from MainWindow
        self.supporter_list: list[Supporter] = supporter_list

    def run(self) -> None:
        try:
            endpoints_config = [
                {
                    "type": "supporters",
                    "price_key": "support_coffee_price",
                    "currency_key": "support_currency",
                },
                {
                    "type": "subscriptions",
                    "price_key": "subscription_coffee_price",
                    "currency_key": "subscription_currency",
                },
            ]

            for config in endpoints_config:
                self._process_endpoint(
                    endpoint_type=config["type"],
                    price_field=config["price_key"],
                    currency_field=config["currency_key"],
                )

        except Exception as e:
            self.signals.error.emit(str(e))
            print(f"Critical error occurred: {e}")
        finally:
            self.session.close()
            self.signals.finished.emit()

    def _process_endpoint(
        self,
        endpoint_type: str,
        price_field: str,
        currency_field: str,
    ) -> None:
        next_page = 1
        base_url = f"https://developers.buymeacoffee.com/api/v1/{endpoint_type}"

        while True:
            try:
                response = self.session.get(
                    url=base_url,
                    params={"page": next_page},
                    timeout=10,
                )

                if not response.ok:
                    break

                try:
                    data = response.json()
                except JSONDecodeError:
                    break

                if "error" in data:
                    break

                supporters = data.get("data", [])
                if not supporters:
                    break

                for supporter in supporters:
                    self._process_supporter(
                        supporter,
                        price_field,
                        currency_field,
                    )

                if data.get("next_page_url"):
                    next_page += 1
                else:
                    break

            except RequestException:
                break

    def _process_supporter(
        self,
        supporter: dict,
        price_field: str,
        currency_field: str,
    ) -> None:
        payer_name = (supporter.get("payer_name") or "Anonymous").strip()

        raw_price = supporter.get(price_field, "0")

        currency = supporter.get(currency_field, "USD")

        supporter_obj = Supporter(payer_name, float(raw_price), currency)
        self.supporter_list.append(supporter_obj)


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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.has_error: bool = False
        self.session = Session()

        # Method that will not be disabled
        self.METHOD_WHITELIST = (self.showMinimized, self.show_supporter_list)
        self.VISABLE_WHITELIST = (self.showMinimized, self.show_supporter_list, self.close)

        self.supporter_visible = False
        self.supporter_task = False

        self.steam_path, self.game_path = self._find_steam_and_game_path()
        self.history = HistoryManager(self.game_path / "AutoLLC.history")
        self.api_mapping = {
            "BepInEx/BepInEx": r"https.*BepInEx-Unity.IL2CPP-win-x64-6.*.zip",
            "LimbusTraditionalMandarin/font": r"https.*LTM_font.*.zip",
            "LimbusTraditionalMandarin/storyline": r"https.*LTM_.*.zip",
        }

        self._get_supporter_list()

        self.supporter_window = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setFixedSize(800, 600)

        self.base = Path.cwd() / "assets"
        self.factory = UIComponentFactory()

        # Basic framework
        self.bg_label = self.factory.create_image_label(
            self,
            QtCore.QRect(0, 0, 790, 600),
            self.base / "BasePlate.png",
        )
        self.outer_frame = self.factory.create_image_label(
            self,
            QtCore.QRect(0, 0, 790, 600),
            self.base / "OuterFrame1.png",
        )
        self.log_frame = self.factory.create_image_label(
            self,
            QtCore.QRect(280, 45, 480, 460),
            self.base / "OuterFrame2.png",
        )

        # Progress bar component
        self.progress_bar_bg = self.factory.create_image_label(
            self,
            QtCore.QRect(55, 520, 680, 50),
            self.base / "BasePlateBar.png",
        )
        self.progress_bar_frame = self.factory.create_image_label(
            self,
            QtCore.QRect(30, 520, 730, 51),
            self.base / "OuterFrameBar.png",
        )

        self.supporter_frame = self.factory.create_image_label(
            self,
            QtCore.QRect(20, 45, 750, 530),
            self.base / "SupporterFrame.png",
        )
        self.supporter_frame.setVisible(False)

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
                self.show_supporter_list,
                icon_size=QtCore.QSize(55, 55),
            ),
        ]

        self.buttons: list[QtWidgets.QPushButton] = []
        for config in btn_configs:
            btn = self.factory.create_button(self, config, self.base)
            btn.clicked.connect(config.callback)
            if config.callback in self.METHOD_WHITELIST:
                btn.setProperty("exclude_disable", True)
            if config.callback in self.VISABLE_WHITELIST and config.text != "離開工具":
                btn.setProperty("exclude_visable", True)
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
        self.log_list.setGeometry(300, 105, 440, 380)
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

        self.supporter_widget = QtWidgets.QWidget(self)
        self.supporter_layout = QtWidgets.QGridLayout(self.supporter_widget)
        self.supporter_layout.setSpacing(10)
        self.supporter_layout.setVerticalSpacing(15)
        self.supporter_layout.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft,
        )

        # Allow slider
        self.supporter_scroll_area = QtWidgets.QScrollArea(self)
        self.supporter_scroll_area.setGeometry(40, 100, 710, 460)
        self.supporter_scroll_area.setWidgetResizable(True)
        self.supporter_scroll_area.setWidget(self.supporter_widget)
        self.supporter_scroll_area.setStyleSheet("background: transparent; border: none;")
        self.supporter_scroll_area.setVisible(False)

        self.hide_uis = [
            self.log_frame,
            self.progress_bar_bg,
            self.progress_bar,
            self.progress_bar_frame,
            self.log_list,
            self.info_label,
            self.supporter_frame,
            self.supporter_scroll_area,
            *(btn for btn in self.buttons if not btn.property("exclude_visable")),
        ]

        # Layer order adjustment
        self.bg_label.lower()
        self.outer_frame.raise_()
        self.log_frame.raise_()
        self.progress_bar_bg.raise_()
        self.progress_bar.raise_()
        self.progress_bar_frame.raise_()
        self.supporter_frame.raise_()
        self.supporter_widget.raise_()

        # Make sure core components are at the top
        self.log_list.raise_()
        self.title_label.raise_()
        self.info_label.raise_()
        for btn in self.buttons:
            btn.raise_()

    @classmethod
    def _find_steam_and_game_path(cls) -> tuple[Path, Path]:
        """Return SteamPath and GamePath."""
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Valve\Steam",
            ) as key:
                steam_path = Path(winreg.QueryValueEx(key, "SteamPath")[0])

            libs = json.loads(
                cls._parse_vdf((steam_path / "steamapps/libraryfolders.vdf").read_text()),
            )
            for lib in libs["libraryfolders"].values():
                if (
                    path := Path(lib["path"]) / "steamapps/common/Limbus Company/LimbusCompany.exe"
                ).exists():
                    return steam_path, path.parent

            raise RuntimeError("Game installation path not found")
        except ModuleNotFoundError:
            raise NotImplementedError("This App only supports Windows systems") from None
        except FileNotFoundError:
            raise FileNotFoundError("Steam not found") from None

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
            response = self.session.get(
                f"https://api.github.com/repos/{api_part}/releases",
                headers=headers,
            )
            response.raise_for_status()
            for asset in response.json()[0]["assets"]:
                url = asset["browser_download_url"]
                if rematch(pattern, url):
                    return url
        except Exception as e:
            self.has_error = True
            self._add_log(f"獲取下載連結失敗: {e!s}")
        return None

    def _get_supporter_list(self) -> None:
        self.supporter_list: list[Supporter] = []
        headers = {"Authorization": f"Bearer {BUY_ME_A_COFFEE_TOKEN}"}
        worker = GetSupporterList(headers, self.supporter_list)
        worker.signals.finished.connect(self._add_supporter_list)
        QThreadPool.globalInstance().start(worker)

    def show_supporter_list(self) -> None:
        for ui in self.hide_uis:
            ui.setVisible(not ui.isVisible())

    def _add_supporter_list(self) -> None:
        self.supporter_task = False

        max_columns = 3
        for i, (supporter) in enumerate(self.supporter_list):
            row = i // max_columns
            col = i % max_columns

            support_data = self.factory.create_supporter_data(
                supporter,
                self.base / "SupporterData.png",
            )

            support_widget = QtWidgets.QWidget()
            support_widget.setSizePolicy(
                QtWidgets.QSizePolicy.Maximum,
                QtWidgets.QSizePolicy.Maximum,
            )
            support_widget.setStyleSheet("border: 0px solid white; padding: 0px;")
            support_widget.setLayout(support_data)
            self.supporter_layout.addWidget(support_widget, row, col)

        self.supporter_widget.setLayout(self.supporter_layout)

    def _on_install_finished(self) -> None:
        self.history.save()
        self._add_log("模組安裝完畢!")
        self._launch_game()

    def _launch_game(self) -> None:
        self._add_log("即將為您啟動遊戲!")
        if not any("steam" in line.lower() for line in popen("tasklist").readlines()):
            subprocess.run([self.steam_path / "steam.exe", "-applaunch", "1973530"], check=False)
        else:
            subprocess.run([str(self.game_path / "LimbusCompany.exe")], check=False)

        for btn in self.buttons:
            btn.setEnabled(True)

        if self.has_error:
            return
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
        self.session.close()
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
