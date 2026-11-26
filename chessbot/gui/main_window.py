import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import chess
from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QDoubleSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..capture import get_capturer
from ..config import Settings, load_settings
from ..control.mouse import Mouse
from ..engine.uci import Book, EngineClient
from ..game import GameSession
from ..vision.recognizer import Recognizer
from .overlay import ChessOverlay


def get_base_path() -> Path:
    """Devuelve la ruta base adecuada tanto para script como para ejecutable congelado."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def find_default_engine() -> str:
    """Busca Stockfish en ubicaciones habituales tanto en Windows como en macOS/Linux."""
    candidates = [
        # Windows
        Path.home() / "OneDrive" / "Desktop" / "stockfish" / "stockfish.exe",
        Path.home() / "Desktop" / "stockfish" / "stockfish.exe",
        get_base_path() / "stockfish.exe",
        Path("stockfish.exe"),
        # macOS (Homebrew / MacPorts / binarios estándar)
        Path("/opt/homebrew/bin/stockfish"),
        Path("/usr/local/bin/stockfish"),
        Path("/usr/bin/stockfish"),
        Path.home() / "stockfish" / "stockfish",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    found = shutil.which("stockfish")
    if found:
        return found
    return ""


class GameWorker(QThread):
    sig_status = pyqtSignal(str)
    sig_board_detected = pyqtSignal(tuple)
    sig_suggest_move = pyqtSignal(object, bool, tuple, str, float)
    sig_clear_suggestion = pyqtSignal()
    sig_position_update = pyqtSignal(str, bool)
    sig_log = pyqtSignal(str)
    sig_finished = pyqtSignal(str)
    sig_error = pyqtSignal(str)

    def __init__(
        self,
        engine_path: str,
        threads: int,
        hash_mb: int,
        depth: int,
        move_time: float,
        depth_mode: bool,
        mode: str,  # 'overlay' or 'play'
        turn_choice: str,  # 'auto', 'white', 'black'
        initial_turn: str = "my_turn",  # 'my_turn', 'auto', 'opponent_turn'
        skill_level: int = 20,
        parent=None,
    ):
        super().__init__(parent)
        self.engine_path = engine_path
        self.threads = threads
        self.hash_mb = hash_mb
        self.depth = depth
        self.move_time = move_time
        self.depth_mode = depth_mode
        self.mode = mode
        self.turn_choice = turn_choice
        self.initial_turn = initial_turn
        self.skill_level = skill_level

        self.session: Optional[GameSession] = None
        self.capturer = None
        self.engine = None
        self._is_stopped = False

    def stop(self):
        self._is_stopped = True
        if self.session:
            self.session.stop()
        if self.engine:
            try:
                self.engine.close()
            except Exception:
                pass
        if self.capturer:
            try:
                self.capturer.close()
            except Exception:
                pass

    def run(self):
        base = get_base_path()
        model_path = base / "models" / "piece_classifier.onnx"
        book_path = base / "assets" / "Performance.bin"

        if not model_path.is_file():
            # Buscar en directorio actual
            model_path = Path("models/piece_classifier.onnx")
        if not book_path.is_file():
            book_path = Path("assets/Performance.bin")

        if not model_path.is_file():
            self.sig_error.emit(f"No se encontró el modelo ONNX en: {model_path}")
            return

        self.sig_log.emit("Iniciando componentes del bot...")
        self.sig_status.emit("Iniciando motor y captura...")

        try:
            self.capturer = get_capturer("auto")
            self.sig_log.emit(f"Capturador iniciado: {self.capturer.name} (Escala: {self.capturer.scale})")
        except Exception as exc:
            self.sig_error.emit(f"Error al iniciar captura de pantalla: {exc}")
            return

        try:
            self.engine = EngineClient(self.engine_path, self.threads, self.hash_mb, skill_level=self.skill_level)
            self.sig_log.emit(f"Motor UCI conectado correctamente (Nivel de habilidad: {self.skill_level}/20).")
        except Exception as exc:
            if self.capturer:
                self.capturer.close()
            self.sig_error.emit(f"Error al iniciar motor UCI ({self.engine_path}): {exc}")
            return

        try:
            book = Book(book_path) if book_path.is_file() else None
            recognizer = Recognizer(model_path=model_path)
            mouse = Mouse(scale=self.capturer.scale)

            turn_arg = None
            if self.initial_turn == "my_turn":
                turn_arg = "my_turn"
            elif self.initial_turn == "opponent_turn":
                turn_arg = "opponent_turn"
            elif self.turn_choice == "white":
                turn_arg = chess.WHITE
            elif self.turn_choice == "black":
                turn_arg = chess.BLACK

            def on_board_det(region):
                self.sig_board_detected.emit(region)
                self.sig_status.emit(f"Tablero detectado: {region}")

            def on_suggest(move, white_bottom, region, eval_text="", eval_val=0.0):
                primary_move = move[0] if isinstance(move, list) and move else str(move)
                self.sig_suggest_move.emit(move, white_bottom, region, eval_text, eval_val)
                eval_tag = f" [{eval_text}]" if eval_text else ""
                self.sig_status.emit(f"🎯 Tu turno: juega {primary_move}{eval_tag}")

            def on_clear():
                self.sig_clear_suggestion.emit()
                self.sig_status.emit("⏳ Esperando respuesta del rival...")

            def on_pos_update(board, white_bottom):
                self.sig_position_update.emit(board.fen(), white_bottom)

            def log_fn(*args):
                msg = " ".join(str(a) for a in args)
                self.sig_log.emit(msg)

            self.session = GameSession(
                capturer=self.capturer,
                engine=self.engine,
                book=book,
                recognizer=recognizer,
                mouse=mouse,
                depth_mode=self.depth_mode,
                depth=self.depth,
                move_time=self.move_time,
                turn_arg=turn_arg,
                mode=self.mode,
                on_board_detected=on_board_det,
                on_suggest_move=on_suggest,
                on_clear_suggestion=on_clear,
                on_position_update=on_pos_update,
                log=log_fn,
                confirm=lambda prompt: "w",  # default confirmation en modo GUI
            )

            self.sig_status.emit("🔍 Buscando tablero de ajedrez en pantalla...")
            self.session.run()

            if not self._is_stopped:
                self.sig_finished.emit("Partida finalizada.")
            else:
                self.sig_finished.emit("Sesión detenida por el usuario.")

        except Exception as exc:
            if not self._is_stopped:
                import traceback
                detail = traceback.format_exc().strip().splitlines()[-1]
                self.sig_error.emit(f"Error durante el juego: {exc}\n\nDetalle: {detail}")
        finally:
            if self.engine:
                try:
                    self.engine.close()
                except Exception:
                    pass
            if self.capturer:
                try:
                    self.capturer.close()
                except Exception:
                    pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chess Assistant")
        self.resize(680, 520)
        self.setMinimumSize(400, 350)

        # Configurar icono de la aplicación
        icon_path = get_base_path() / "assets" / "icon.png"
        if not icon_path.is_file():
            icon_path = Path("assets/icon.png")
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.overlay: Optional[ChessOverlay] = None
        self.worker: Optional[GameWorker] = None

        self._setup_ui()
        self._apply_styles()
        self._init_overlay()

    def _init_overlay(self):
        self.overlay = ChessOverlay()
        # Posicionar el overlay para cubrir la pantalla completa
        screen = QApplication.primaryScreen()
        if screen:
            self.overlay.setGeometry(screen.geometry())
        self.overlay.show()

    def _setup_ui(self):
        # Cabecera, info y botones quedan fijos; sólo el contenido de las
        # pestañas hace scroll cuando la ventana se achica.
        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. Cabecera
        header = QFrame()
        header.setObjectName("HeaderFrame")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 10, 12, 10)

        title_box = QVBoxLayout()
        title_lbl = QLabel("♟️ Chess Assistant")
        title_lbl.setObjectName("MainTitle")
        subtitle_lbl = QLabel("Asistente visual de ajedrez con overlay y Stockfish UCI | Desarrollado por Tomás Ábalos")
        subtitle_lbl.setObjectName("Subtitle")
        subtitle_lbl.setWordWrap(True)
        title_box.addWidget(title_lbl)
        title_box.addWidget(subtitle_lbl)
        h_layout.addLayout(title_box, 1)

        self.status_badge = QLabel("Listo")
        self.status_badge.setObjectName("StatusBadge")
        self.status_badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h_layout.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        main_layout.addWidget(header)

        # 2. Selección de Modo de Operación
        mode_box = QGroupBox("Modo de Operación")
        mode_layout = QVBoxLayout(mode_box)

        self.rb_overlay = QRadioButton("🎯 Modo Asistente / Overlay (Solo sugerir)")
        self.rb_overlay.setToolTip("Muestra flechas y casillas sobre el tablero sin hacer clics automáticos.")
        self.rb_overlay.setChecked(True)

        self.rb_play = QRadioButton("🤖 Modo Automático (El bot realiza los clics)")
        self.rb_play.setToolTip("El bot clica automáticamente en las casillas.")

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.rb_overlay)
        self.mode_group.addButton(self.rb_play)

        mode_layout.addWidget(self.rb_overlay)
        mode_layout.addWidget(self.rb_play)
        mode_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._mode_box = mode_box
        self._mode_layout = mode_layout
        main_layout.addWidget(mode_box)

        # 3. Pestañas de Configuración
        tabs = QTabWidget()

        # Pestaña 1: Configuración Visual del Overlay
        tab_visual = QWidget()
        v_layout = QGridLayout(tab_visual)

        self.cb_arrow = QCheckBox("Dibujar Flechas de Movimiento")
        self.cb_arrow.setChecked(True)
        self.cb_arrow.toggled.connect(self._update_overlay_settings)

        self.cb_squares = QCheckBox("Resaltar Casilla Origen y Destino")
        self.cb_squares.setChecked(True)
        self.cb_squares.toggled.connect(self._update_overlay_settings)

        self.cb_badge = QCheckBox("Mostrar Etiqueta de Notación (e.g. e2➔e4)")
        self.cb_badge.setChecked(True)
        self.cb_badge.toggled.connect(self._update_overlay_settings)

        self.cb_border = QCheckBox("Mostrar Marco del Tablero Detectado")
        self.cb_border.setChecked(True)
        self.cb_border.toggled.connect(self._update_overlay_settings)

        self.cb_eval_bar = QCheckBox("📊 Mostrar Barra de Ventaja / Evaluación")
        self.cb_eval_bar.setChecked(True)
        self.cb_eval_bar.toggled.connect(self._update_overlay_settings)

        self.cb_multipv = QCheckBox("🥉 Mostrar Top 3 Mejores Jugadas")
        self.cb_multipv.setChecked(True)
        self.cb_multipv.toggled.connect(self._update_overlay_settings)

        self.cb_sound = QCheckBox("🔊 Sonido de Notificación al Sugerir")
        self.cb_sound.setChecked(True)

        # Los checkboxes se reacomodan en 1 o 2 columnas según el ancho (ver _reflow_layout)
        self._visual_layout = v_layout
        self._visual_checks = [
            self.cb_arrow, self.cb_squares, self.cb_badge, self.cb_border,
            self.cb_eval_bar, self.cb_multipv, self.cb_sound,
        ]
        self._visual_columns = 0

        self.lbl_theme = QLabel("Color del Overlay:")
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Verde Clásico (Lichess/Chess.com)", "Azul Moderno", "Dorado / Ámbar", "Neón Púrpura"])
        self.combo_theme.currentIndexChanged.connect(self._update_overlay_settings)

        tabs.addTab(self._make_scrollable(tab_visual), "🎨 Overlay")

        # Pestaña 2: Motor de Ajedrez
        tab_engine = QWidget()
        e_layout = QGridLayout(tab_engine)

        e_layout.addWidget(QLabel("Ruta del Motor UCI:"), 0, 0)
        self.txt_engine = QLineEdit()
        self.txt_engine.setText(find_default_engine())
        self.btn_browse = QPushButton("Examinar...")
        self.btn_browse.clicked.connect(self._browse_engine)
        h_eng = QHBoxLayout()
        h_eng.addWidget(self.txt_engine)
        h_eng.addWidget(self.btn_browse)
        e_layout.addLayout(h_eng, 0, 1, 1, 3)

        e_layout.addWidget(QLabel("Profundidad fija:"), 1, 0)
        self.spin_depth = QSpinBox()
        self.spin_depth.setRange(1, 35)
        self.spin_depth.setValue(10)
        e_layout.addWidget(self.spin_depth, 1, 1)

        self.cb_depth_mode = QCheckBox("Modo Profundidad fija (ignorar tiempo)")
        e_layout.addWidget(self.cb_depth_mode, 1, 2, 1, 2)

        e_layout.addWidget(QLabel("Velocidad del motor:"), 2, 0)
        self.combo_speed = QComboBox()
        self.combo_speed.addItems([
            "⚡ Casi Instantáneo (0.05s / 50ms - Recomendado)",
            "🚀 Rápido (0.2s)",
            "🧠 Moderado (0.5s)",
            "🏆 Torneo / Profundo (2.0s)",
        ])
        e_layout.addWidget(self.combo_speed, 2, 1, 1, 3)

        e_layout.addWidget(QLabel("Tiempo exacto (s):"), 3, 0)
        self.spin_time = QDoubleSpinBox()
        self.spin_time.setRange(0.02, 60.0)
        self.spin_time.setSingleStep(0.05)
        self.spin_time.setValue(0.05)
        e_layout.addWidget(self.spin_time, 3, 1)

        self.combo_speed.currentIndexChanged.connect(
            lambda idx: self.spin_time.setValue([0.05, 0.20, 0.50, 2.0][idx])
        )

        e_layout.addWidget(QLabel("Hilos CPU:"), 4, 0)
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 64)
        self.spin_threads.setValue(max(1, (os.cpu_count() or 4) - 1))
        e_layout.addWidget(self.spin_threads, 4, 1)

        e_layout.addWidget(QLabel("Memoria Hash (MB):"), 4, 2)
        self.spin_hash = QSpinBox()
        self.spin_hash.setRange(16, 16384)
        self.spin_hash.setValue(512)
        e_layout.addWidget(self.spin_hash, 4, 3)

        e_layout.addWidget(QLabel("Dificultad / Nivel de ELO:"), 5, 0)
        self.combo_skill = QComboBox()
        self.combo_skill.addItems([
            "🏆 Gran Maestro / Máximo ELO 3200+ (Skill 20)",
            "🥇 Maestro Internacional ~2400 ELO (Skill 16)",
            "🥈 Jugador de Club ~1800 ELO (Skill 11)",
            "🥉 Jugador Casual ~1400 ELO (Skill 6)",
            "🌱 Principiante / Fácil ~1000 ELO (Skill 1)",
        ])
        e_layout.addWidget(self.combo_skill, 5, 1, 1, 3)

        e_layout.setColumnStretch(1, 1)
        e_layout.setColumnStretch(3, 1)
        tabs.addTab(self._make_scrollable(tab_engine), "⚙️ Motor")

        # Pestaña 3: Configuración de Partida
        tab_game = QWidget()
        g_layout = QGridLayout(tab_game)

        g_layout.addWidget(QLabel("Bando / Perspectiva:"), 0, 0)
        self.combo_turn = QComboBox()
        self.combo_turn.addItems(["Auto-detectar (lado inferior del tablero)", "Jugar con Blancas", "Jugar con Negras"])
        g_layout.addWidget(self.combo_turn, 0, 1)

        g_layout.addWidget(QLabel("¿De quién es el turno al iniciar?:"), 1, 0)
        self.combo_initial_turn = QComboBox()
        self.combo_initial_turn.addItems([
            "🎯 Es mi turno (Sugerir movimiento ya)",
            "🔍 Auto-detectar según la posición en pantalla",
            "⏳ Es turno del rival (Esperar jugada del rival)",
        ])
        g_layout.addWidget(self.combo_initial_turn, 1, 1)

        g_layout.setColumnStretch(1, 1)
        g_layout.setRowStretch(2, 1)
        tabs.addTab(self._make_scrollable(tab_game), "♟️ Juego")

        tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tabs.setUsesScrollButtons(True)
        tabs.setMinimumHeight(100)
        main_layout.addWidget(tabs, 1)

        # Combos: que no fuercen un ancho mínimo enorme por sus textos largos
        for combo in (self.combo_theme, self.combo_speed, self.combo_skill,
                      self.combo_turn, self.combo_initial_turn):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            combo.view().setMinimumWidth(combo.view().sizeHintForColumn(0) + 30)

        self.txt_engine.setMinimumWidth(80)
        self._reflow_visual_checks(2)

        # 4. Indicador de Jugada Actual y FEN
        info_frame = QFrame()
        info_frame.setObjectName("InfoFrame")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(16, 16, 16, 16)
        info_layout.setSpacing(8)

        self.lbl_move = QLabel("Sugerencia: —")
        self.lbl_move.setObjectName("MoveSuggestion")
        self.lbl_move.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_move.setWordWrap(True)
        info_layout.addWidget(self.lbl_move)

        self.lbl_fen = QLabel("FEN: Posición inicial")
        self.lbl_fen.setObjectName("FenLabel")
        self.lbl_fen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_fen.setWordWrap(True)
        self.lbl_fen.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addWidget(self.lbl_fen)

        info_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        main_layout.addWidget(info_frame)

        # 5. Botones de Control Principal
        btn_layout = QHBoxLayout()

        self.btn_start = QPushButton("▶ Iniciar Asistente")
        self.btn_start.setObjectName("StartButton")
        self.btn_start.clicked.connect(self._start_game)

        self.btn_stop = QPushButton("⏹ Detener")
        self.btn_stop.setObjectName("StopButton")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_game)

        btn_layout.addWidget(self.btn_start, 2)
        btn_layout.addWidget(self.btn_stop, 1)
        main_layout.addLayout(btn_layout)

        self._main_layout = main_layout
        self._header_layout = h_layout
        self._info_layout = info_layout
        self._info_frame = info_frame
        self._title_lbl = title_lbl
        self._subtitle_lbl = subtitle_lbl
        self._compact = None

    # ------------------------------------------------------------------ #
    # Diseño responsive
    # ------------------------------------------------------------------ #
    @staticmethod
    def _make_scrollable(widget: QWidget) -> QScrollArea:
        """Envuelve una pestaña en un QScrollArea para que nunca se recorte."""
        area = QScrollArea()
        area.setWidget(widget)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setStyleSheet("QScrollArea { background: transparent; } "
                           "QScrollArea > QWidget > QWidget { background: transparent; }")
        return area

    def _reflow_visual_checks(self, columns: int):
        """Reubica los checkboxes del overlay en 1 o 2 columnas."""
        if columns == self._visual_columns:
            return
        self._visual_columns = columns
        layout = self._visual_layout
        for w in self._visual_checks + [self.lbl_theme, self.combo_theme]:
            layout.removeWidget(w)
        for i, cb in enumerate(self._visual_checks):
            layout.addWidget(cb, i // columns, i % columns)
        row = (len(self._visual_checks) + columns - 1) // columns
        if columns == 1:
            layout.addWidget(self.lbl_theme, row, 0)
            layout.addWidget(self.combo_theme, row + 1, 0)
        else:
            layout.addWidget(self.lbl_theme, row, 0)
            layout.addWidget(self.combo_theme, row, 1)

    def _apply_compact_mode(self, compact: bool):
        """Reduce márgenes, fuentes y textos cuando la ventana es chica."""
        if compact == self._compact:
            return
        self._compact = compact
        m = 8 if compact else 16
        self._main_layout.setContentsMargins(m, m, m, m)
        self._main_layout.setSpacing(6 if compact else 12)
        self._info_layout.setContentsMargins(8 if compact else 16, 4 if compact else 16,
                                             8 if compact else 16, 4 if compact else 16)
        self._subtitle_lbl.setVisible(not compact)
        self.btn_start.setText("▶ Iniciar" if compact else "▶ Iniciar Asistente")
        self.btn_stop.setText("⏹" if compact else "⏹ Detener")
        self._mode_box.setTitle("" if compact else "Modo de Operación")
        self.rb_overlay.setText("🎯 Asistente (Overlay)" if compact else "🎯 Modo Asistente / Overlay (Solo sugerir)")
        self.rb_play.setText("🤖 Automático" if compact else "🤖 Modo Automático (El bot realiza los clics)")
        self._mode_layout.setDirection(
            QHBoxLayout.Direction.LeftToRight if compact else QHBoxLayout.Direction.TopToBottom)
        self._mode_box.setStyleSheet(
            "QGroupBox { margin-top: 0px; padding-top: 2px; }" if compact else "")
        self._info_frame.setStyleSheet("#InfoFrame { padding: 0px 6px; }" if compact else "")
        self._info_layout.setSpacing(2 if compact else 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        self._reflow_visual_checks(1 if w < 600 else 2)
        self._apply_compact_mode(w < 520 or self.height() < 490)

    def _browse_engine(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar ejecutable del motor UCI",
            "",
            "Ejecutables (*.exe);;Todos los archivos (*.*)",
        )
        if path:
            self.txt_engine.setText(path)

    def _update_overlay_settings(self):
        if not self.overlay:
            return
        self.overlay.show_arrow = self.cb_arrow.isChecked()
        self.overlay.show_squares = self.cb_squares.isChecked()
        self.overlay.show_badge = self.cb_badge.isChecked()
        self.overlay.show_board_border = self.cb_border.isChecked()
        self.overlay.show_eval_bar = self.cb_eval_bar.isChecked()
        self.overlay.show_multipv = self.cb_multipv.isChecked()

        idx = self.combo_theme.currentIndex()
        theme_names = ["green", "blue", "gold", "neon"]
        self.overlay.theme = theme_names[idx] if idx < len(theme_names) else "green"
        self.overlay.update()

    def _start_game(self):
        engine_path = self.txt_engine.text().strip()
        if not engine_path or not Path(engine_path).is_file():
            QMessageBox.critical(
                self,
                "Motor no encontrado",
                f"No se encontró el ejecutable del motor en:\n{engine_path}\n\n"
                "Por favor selecciona una ruta válida a Stockfish mediante el botón 'Examinar...'.",
            )
            return

        mode = "overlay" if self.rb_overlay.isChecked() else "play"
        turn_map = {0: "auto", 1: "white", 2: "black"}
        turn_choice = turn_map[self.combo_turn.currentIndex()]

        initial_turn_map = {0: "my_turn", 1: "auto", 2: "opponent_turn"}
        initial_turn = initial_turn_map[self.combo_initial_turn.currentIndex()]

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_badge.setText("Ejecutando")
        self.status_badge.setStyleSheet("background-color: #10B981; color: white;")
        if hasattr(self, "txt_log") and self.txt_log is not None:
            self.txt_log.clear()

        self._update_overlay_settings()

        skill_levels = [20, 16, 11, 6, 1]
        chosen_skill = skill_levels[min(self.combo_skill.currentIndex(), len(skill_levels) - 1)]

        self.worker = GameWorker(
            engine_path=engine_path,
            threads=self.spin_threads.value(),
            hash_mb=self.spin_hash.value(),
            depth=self.spin_depth.value(),
            move_time=self.spin_time.value(),
            depth_mode=self.cb_depth_mode.isChecked(),
            mode=mode,
            turn_choice=turn_choice,
            initial_turn=initial_turn,
            skill_level=chosen_skill,
        )

        self.worker.sig_status.connect(self._on_status)
        self.worker.sig_board_detected.connect(self._on_board_detected)
        self.worker.sig_suggest_move.connect(self._on_suggest_move)
        self.worker.sig_clear_suggestion.connect(self._on_clear_suggestion)
        self.worker.sig_position_update.connect(self._on_position_update)
        self.worker.sig_log.connect(self._on_log)
        self.worker.sig_finished.connect(self._on_finished)
        self.worker.sig_error.connect(self._on_error)

        self.worker.start()

    def _stop_game(self):
        if self.worker:
            self.status_badge.setText("Deteniendo...")
            self.status_badge.setStyleSheet("background-color: #F59E0B; color: white;")
            self.worker.stop()
            self.btn_stop.setEnabled(False)

    def _on_status(self, text: str):
        self.statusBar().showMessage(text)

    def _on_board_detected(self, region: tuple):
        if self.overlay and self.worker and self.worker.capturer:
            self.overlay.set_scale(self.worker.capturer.scale)
            self.overlay.set_board_region(region)

    def _on_suggest_move(self, move: str | list[str], white_at_bottom: bool, region: tuple, eval_text: str = "", eval_val: float = 0.0):
        scale = self.worker.capturer.scale if (self.worker and self.worker.capturer) else 1.0
        if self.overlay:
            self.overlay.set_suggestion(move, white_at_bottom, region, scale, eval_str=eval_text, eval_val=eval_val)

        # Reproducir sonido suave si está activado
        if hasattr(self, "cb_sound") and self.cb_sound.isChecked():
            try:
                QApplication.beep()
            except Exception:
                pass

        primary = move[0] if isinstance(move, list) and move else str(move)
        origin = primary[:2].upper()
        dest = primary[2:4].upper()
        promo = f"={primary[4:].upper()}" if len(primary) > 4 else ""

        eval_display = f"   |   Eval: {eval_text}" if eval_text else ""
        if isinstance(move, list) and len(move) > 1:
            alt_moves = ", ".join(m.upper() for m in move[1:3])
            self.lbl_move.setText(f"🎯 Sugerencia: {origin} ➔ {dest}{promo}{eval_display}\n<span style='font-size:14px; color:#94A3B8;'>Alternativas: {alt_moves}</span>")
        else:
            self.lbl_move.setText(f"🎯 Sugerencia: {origin}  ➔  {dest}{promo}{eval_display}")
        self.lbl_move.setStyleSheet("color: #38BDF8; font-weight: bold; font-size: 22px;")

    def _on_clear_suggestion(self):
        if self.overlay:
            self.overlay.clear_suggestion()
        self.lbl_move.setText("⏳ Esperando movimiento del rival...")
        self.lbl_move.setStyleSheet("color: #94A3B8; font-weight: normal; font-size: 18px;")

    def _on_position_update(self, fen: str, white_at_bottom: bool):
        short_fen = fen.split(" ")[0]
        self.lbl_fen.setText(f"Posición: {short_fen}")

    def _on_log(self, text: str):
        if hasattr(self, "txt_log") and self.txt_log is not None:
            self.txt_log.append(text)
            sb = self.txt_log.verticalScrollBar()
            if sb:
                sb.setValue(sb.maximum())

    def _on_finished(self, msg: str):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_badge.setText("Listo")
        self.status_badge.setStyleSheet("background-color: #64748B; color: white;")
        if self.overlay:
            self.overlay.clear_suggestion()
            self.overlay.set_board_region(None)
        self._on_log(f"--- {msg} ---")

    def _on_error(self, err_msg: str):
        self._on_finished("Error")
        self.status_badge.setText("Error")
        self.status_badge.setStyleSheet("background-color: #EF4444; color: white;")
        QMessageBox.critical(self, "Error de Ejecución", err_msg)

    def keyPressEvent(self, event):
        """Atajos de teclado rápidos (Hotkeys)."""
        key = event.key()
        if key == Qt.Key.Key_F6:
            # Alternar visibilidad del overlay
            if self.overlay:
                if self.overlay.isVisible():
                    self.overlay.hide()
                    self.statusBar().showMessage("Overlay oculto (Presiona F6 para mostrar)", 3000)
                else:
                    self.overlay.show()
                    self.statusBar().showMessage("Overlay visible", 3000)
        elif key == Qt.Key.Key_F7:
            # Recalcular / re-sincronizar tablero
            if self.worker and self.worker.isRunning() and self.worker.session:
                self.statusBar().showMessage("Forzando re-lectura del tablero...", 3000)
                try:
                    self.worker.session._resync()
                except Exception:
                    pass
        elif key == Qt.Key.Key_F8:
            # Iniciar o Detener sesión
            if self.worker and self.worker.isRunning():
                self._stop_game()
            else:
                self._start_game()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)
        if self.overlay:
            self.overlay.close()
        event.accept()

    def _apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, #CentralWidget, QScrollArea {
                background-color: #0F172A;
            }
            QWidget {
                color: #F8FAFC;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
            }
            #HeaderFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1E293B, stop:1 #334155);
                border-radius: 8px;
                border: 1px solid #475569;
            }
            #MainTitle {
                font-size: 18px;
                font-weight: bold;
                color: #38BDF8;
            }
            #Subtitle {
                font-size: 12px;
                color: #94A3B8;
            }
            #StatusBadge {
                background-color: #64748B;
                color: white;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 12px;
                font-size: 12px;
            }
            QGroupBox {
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 14px;
                padding-top: 14px;
                font-weight: bold;
                color: #E2E8F0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QTabWidget::pane {
                border: 1px solid #334155;
                border-radius: 8px;
                background-color: #1E293B;
                padding: 10px;
            }
            QTabBar::tab {
                background-color: #0F172A;
                color: #94A3B8;
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #1E293B;
                color: #38BDF8;
                font-weight: bold;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background-color: #0F172A;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px 10px;
                color: #F8FAFC;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #38BDF8;
            }
            QPushButton {
                background-color: #334155;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background-color: #475569;
            }
            #StartButton {
                background-color: #059669;
                border: 1px solid #10B981;
                font-size: 15px;
                padding: 10px;
            }
            #StartButton:hover {
                background-color: #10B981;
            }
            #StartButton:disabled {
                background-color: #1E293B;
                border-color: #334155;
                color: #64748B;
            }
            #StopButton {
                background-color: #DC2626;
                border: 1px solid #EF4444;
                font-size: 15px;
                padding: 10px;
            }
            #StopButton:hover {
                background-color: #EF4444;
            }
            #StopButton:disabled {
                background-color: #1E293B;
                border-color: #334155;
                color: #64748B;
            }
            #InfoFrame {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 12px;
            }
            #MoveSuggestion {
                font-size: 16px;
                font-weight: bold;
                color: #10B981;
            }
            #FenLabel {
                font-size: 11px;
                color: #94A3B8;
                font-family: 'Consolas', monospace;
            }
            #LogConsole {
                background-color: #020617;
                border: 1px solid #1E293B;
                border-radius: 6px;
                font-family: 'Consolas', monospace;
                font-size: 12px;
                color: #CBD5E1;
            }
        """)


def run_gui():
    # En Windows, un AppUserModelID propio hace que la barra de tareas muestre
    # nuestro logo en lugar del icono de Python (cuando se lanza con pythonw).
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TomasAbalos.ChessAssistant")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    for name in ("icon.ico", "icon.png"):
        icon_path = get_base_path() / "assets" / name
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
            break
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
