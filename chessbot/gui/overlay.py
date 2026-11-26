import math
import sys
from typing import Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import QApplication, QWidget

from ..vision.squares import square_center, square_name_to_row_col


def make_window_click_through(widget: QWidget) -> None:
    """Configura la ventana en Windows para que los clics del ratón la atraviesen y sea invisible a capturas de pantalla."""
    if sys.platform != "win32":
        return
    import ctypes

    hwnd = int(widget.winId())
    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_LAYERED = 0x00080000

    user32 = ctypes.windll.user32
    try:
        get_long = user32.GetWindowLongPtrW
        set_long = user32.SetWindowLongPtrW
    except AttributeError:
        get_long = user32.GetWindowLongW
        set_long = user32.SetWindowLongW

    style = get_long(hwnd, GWL_EXSTYLE)
    set_long(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)

    # Excluir el overlay de capturas de pantalla (dxcam, mss, OBS)
    # WDA_EXCLUDEFROMCAPTURE = 0x00000011 (Windows 10 v2004+ y Windows 11)
    if hasattr(user32, "SetWindowDisplayAffinity"):
        try:
            user32.SetWindowDisplayAffinity(hwnd, 0x11)
        except Exception:
            pass


class ChessOverlay(QWidget):
    """Overlay transparente de alta precisión sobre la pantalla para sugerir jugadas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.current_moves: list[str] = []
        self.eval_str: str = ""
        self.eval_val: float = 0.0
        self.white_at_bottom: bool = True
        self.board_region: Optional[Tuple[int, int, int, int]] = None
        self.scale: float = 1.0

        # Opciones visuales
        self.show_arrow: bool = True
        self.show_squares: bool = True
        self.show_badge: bool = True
        self.show_board_border: bool = True
        self.show_eval_bar: bool = True
        self.show_multipv: bool = True
        self.theme: str = "green"  # 'green', 'blue', 'gold', 'neon'

        self._click_through_set = False

    @property
    def current_move(self) -> Optional[str]:
        return self.current_moves[0] if self.current_moves else None

    @current_move.setter
    def current_move(self, val: Optional[str]):
        self.current_moves = [val] if val else []

    def showEvent(self, event):
        super().showEvent(event)
        if not self._click_through_set:
            make_window_click_through(self)
            self._click_through_set = True

    def set_scale(self, scale: float) -> None:
        self.scale = max(0.1, scale)
        self.update()

    def set_board_region(self, region: Optional[Tuple[int, int, int, int]]) -> None:
        self.board_region = region
        self.update()

    def set_suggestion(
        self,
        move: str | list[str],
        white_at_bottom: bool,
        region: Tuple[int, int, int, int],
        scale: float = 1.0,
        eval_str: str = "",
        eval_val: float = 0.0,
    ) -> None:
        if isinstance(move, list):
            self.current_moves = move
        else:
            self.current_moves = [move] if move else []
        self.eval_str = eval_str
        self.eval_val = eval_val
        self.white_at_bottom = white_at_bottom
        self.board_region = region
        self.scale = scale
        self.update()

    def clear_suggestion(self) -> None:
        self.current_moves = []
        self.eval_str = ""
        self.eval_val = 0.0
        self.update()

    def _get_square_rect(self, square_name: str) -> Optional[QRectF]:
        if not self.board_region:
            return None
        left, top, right, bottom = self.board_region
        s = self.scale
        # Coordenadas escaladas a píxeles de pantalla DIP
        l, t, r, b = left / s, top / s, right / s, bottom / s
        w = (r - l) / 8.0
        h = (b - t) / 8.0

        row, col = square_name_to_row_col(square_name, self.white_at_bottom)
        x = l + col * w
        y = t + row * h
        return QRectF(x, y, w, h)

    def _get_square_center(self, square_name: str) -> Optional[QPointF]:
        rect = self._get_square_rect(square_name)
        if rect:
            return rect.center()
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Dibujar contorno del tablero si está detectado
        if self.show_board_border and self.board_region:
            left, top, right, bottom = self.board_region
            s = self.scale
            bx, by, bw, bh = left / s, top / s, (right - left) / s, (bottom - top) / s
            board_rect = QRectF(bx - 4, by - 4, bw + 8, bh + 8)
            border_pen = QPen(QColor(59, 130, 246, 160), 2.5, Qt.PenStyle.DashLine)
            painter.setPen(border_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(board_rect, 8, 8)

            # Dibujar barra de evaluación (Eval Bar) a la izquierda del tablero
            if self.show_eval_bar and self.eval_str:
                self._draw_eval_bar(painter, bx, by, bh)

        # 2. Si no hay jugadas sugeridas, terminar aquí
        if not self.current_moves:
            return

        moves_to_draw = self.current_moves[:3] if self.show_multipv else self.current_moves[:1]

        # Paleta de colores para Top 1, Top 2 y Top 3
        # Rank 0 (Mejor jugada): Verde esmeralda brillante
        # Rank 1 (Segunda jugada): Azul eléctrico
        # Rank 2 (Tercera jugada): Amarillo/Ámbar
        rank_styles = [
            {
                "arrow": QColor(34, 197, 94, 235),
                "from_bg": QColor(234, 179, 8, 120),
                "from_border": QColor(202, 138, 4, 220),
                "to_bg": QColor(34, 197, 94, 150),
                "to_border": QColor(22, 163, 74, 255),
            },
            {
                "arrow": QColor(56, 189, 248, 200),
                "from_bg": QColor(56, 189, 248, 80),
                "from_border": QColor(14, 165, 233, 180),
                "to_bg": QColor(56, 189, 248, 110),
                "to_border": QColor(2, 132, 199, 220),
            },
            {
                "arrow": QColor(251, 191, 36, 190),
                "from_bg": QColor(251, 191, 36, 70),
                "from_border": QColor(217, 119, 6, 170),
                "to_bg": QColor(251, 191, 36, 100),
                "to_border": QColor(180, 83, 9, 200),
            },
        ]

        # Dibujar en orden inverso (Top 3 -> Top 1) para que la flecha principal quede arriba
        for idx in reversed(range(len(moves_to_draw))):
            mv = moves_to_draw[idx]
            if len(mv) < 4:
                continue

            sq_from = mv[:2]
            sq_to = mv[2:4]
            promo = mv[4:5] if len(mv) == 5 else ""

            rect_from = self._get_square_rect(sq_from)
            rect_to = self._get_square_rect(sq_to)
            pt_from = self._get_square_center(sq_from)
            pt_to = self._get_square_center(sq_to)

            if not rect_from or not rect_to or not pt_from or not pt_to:
                continue

            style = rank_styles[min(idx, len(rank_styles) - 1)]

            # 3. Dibujar casillas resaltadas (solo para la jugada principal o con menor opacidad)
            if self.show_squares and idx == 0:
                pad = 2.0
                r_from = rect_from.adjusted(pad, pad, -pad, -pad)
                painter.setPen(QPen(style["from_border"], 2.5))
                painter.setBrush(QBrush(style["from_bg"]))
                painter.drawRoundedRect(r_from, 6, 6)

                r_to = rect_to.adjusted(pad, pad, -pad, -pad)
                painter.setPen(QPen(style["to_border"], 3.0))
                painter.setBrush(QBrush(style["to_bg"]))
                painter.drawRoundedRect(r_to, 6, 6)

            # 4. Dibujar Flechas
            if self.show_arrow:
                scale_shaft = 1.0 if idx == 0 else 0.7
                self._draw_arrow(painter, pt_from, pt_to, style["arrow"], rect_to.width() * scale_shaft)

            # 5. Dibujar Badge informativo solo para la jugada principal
            if self.show_badge and idx == 0:
                promo_text = f"={promo.upper()}" if promo else ""
                badge_text = f"{sq_from}➔{sq_to}{promo_text}"
                if self.eval_str:
                    badge_text += f" ({self.eval_str})"
                self._draw_badge(painter, rect_to, badge_text, style["to_border"])

    def _draw_eval_bar(self, painter: QPainter, bx: float, by: float, bh: float) -> None:
        """Dibuja una barra de evaluación vertical estilo Lichess/Chess.com al lado del tablero."""
        bar_w = 18.0
        bar_x = bx - bar_w - 12.0
        if bar_x < 5:
            bar_x = bx + 5

        bar_rect = QRectF(bar_x, by, bar_w, bh)

        # Calcular porcentaje de blancas vs negras
        # Sigmoide centrado en 0.0 (eval en peones)
        val = self.eval_val
        # Si estamos jugando con negras invertimos la perspectiva si es necesario o mostramos ventaja absoluta
        # Por convención chess: positivo es ventaja blancas
        win_chance = 1.0 / (1.0 + math.exp(-0.4 * val)) if abs(val) < 50 else (1.0 if val > 0 else 0.0)

        # Altura de la porción blanca
        white_h = bh * win_chance
        black_h = bh - white_h

        # Fondo negras (arriba si blancas abajo)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.white_at_bottom:
            painter.setBrush(QBrush(QColor(30, 41, 59)))
            painter.drawRoundedRect(bar_rect, 4, 4)
            # Porción blancas (abajo)
            white_rect = QRectF(bar_x, by + black_h, bar_w, white_h)
            painter.setBrush(QBrush(QColor(241, 245, 249)))
            painter.drawRoundedRect(white_rect, 4, 4)
        else:
            painter.setBrush(QBrush(QColor(241, 245, 249)))
            painter.drawRoundedRect(bar_rect, 4, 4)
            black_rect = QRectF(bar_x, by + white_h, bar_w, black_h)
            painter.setBrush(QBrush(QColor(30, 41, 59)))
            painter.drawRoundedRect(black_rect, 4, 4)

        # Borde exterior de la barra
        painter.setPen(QPen(QColor(148, 163, 184, 180), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(bar_rect, 4, 4)

        # Etiqueta con el puntaje
        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(56, 189, 248))
        eval_lbl_rect = QRectF(bar_x - 16, by + bh + 4, bar_w + 32, 18)
        painter.drawText(eval_lbl_rect, Qt.AlignmentFlag.AlignCenter, self.eval_str)

    def _draw_arrow(
        self,
        painter: QPainter,
        p_start: QPointF,
        p_end: QPointF,
        color: QColor,
        sq_size: float,
    ) -> None:
        dx = p_end.x() - p_start.x()
        dy = p_end.y() - p_start.y()
        dist = math.hypot(dx, dy)
        if dist < 10:
            return

        angle = math.atan2(dy, dx)

        # Dimensiones dinámicas según el tamaño de casilla
        shaft_width = max(8.0, sq_size * 0.18)
        head_length = max(18.0, sq_size * 0.40)
        head_width = max(22.0, sq_size * 0.48)

        # Acortar inicio y fin para no tapar los centros exactos
        margin_start = sq_size * 0.15
        margin_end = sq_size * 0.18

        x0 = p_start.x() + margin_start * math.cos(angle)
        y0 = p_start.y() + margin_start * math.sin(angle)
        x1 = p_end.x() - margin_end * math.cos(angle)
        y1 = p_end.y() - margin_end * math.sin(angle)

        actual_dist = math.hypot(x1 - x0, y1 - y0)
        if actual_dist < head_length:
            head_length = actual_dist * 0.6

        # Puntos de la cabeza de la flecha
        p_tip = QPointF(x1, y1)
        base_x = x1 - head_length * math.cos(angle)
        base_y = y1 - head_length * math.sin(angle)

        norm_x = -math.sin(angle)
        norm_y = math.cos(angle)

        p_left = QPointF(
            base_x + (head_width / 2.0) * norm_x,
            base_y + (head_width / 2.0) * norm_y,
        )
        p_right = QPointF(
            base_x - (head_width / 2.0) * norm_x,
            base_y - (head_width / 2.0) * norm_y,
        )

        # Shaft (cuerpo de la flecha)
        p_shaft_l_start = QPointF(
            x0 + (shaft_width / 2.0) * norm_x,
            y0 + (shaft_width / 2.0) * norm_y,
        )
        p_shaft_r_start = QPointF(
            x0 - (shaft_width / 2.0) * norm_x,
            y0 - (shaft_width / 2.0) * norm_y,
        )
        p_shaft_l_end = QPointF(
            base_x + (shaft_width / 2.0) * norm_x,
            base_y + (shaft_width / 2.0) * norm_y,
        )
        p_shaft_r_end = QPointF(
            base_x - (shaft_width / 2.0) * norm_x,
            base_y - (shaft_width / 2.0) * norm_y,
        )

        path = QPainterPath()
        path.moveTo(p_shaft_l_start)
        path.lineTo(p_shaft_l_end)
        path.lineTo(p_left)
        path.lineTo(p_tip)
        path.lineTo(p_right)
        path.lineTo(p_shaft_r_end)
        path.lineTo(p_shaft_r_start)
        path.closeSubpath()

        # Dibujar con borde oscuro para que resalte en cualquier tablero
        outline_pen = QPen(QColor(15, 23, 42, 210), 3.0, Qt.PenStyle.SolidLine)
        painter.setPen(outline_pen)
        painter.setBrush(QBrush(color))
        painter.drawPath(path)

    def _draw_badge(
        self,
        painter: QPainter,
        target_rect: QRectF,
        text: str,
        bg_color: QColor,
    ) -> None:
        font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        painter.setFont(font)

        badge_w = 64
        badge_h = 24
        # Ubicar sobre la casilla destino
        bx = target_rect.center().x() - badge_w / 2
        by = target_rect.top() - badge_h - 4
        if by < 10:
            by = target_rect.bottom() + 4

        badge_rect = QRectF(bx, by, badge_w, badge_h)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 1.5))
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(badge_rect, 5, 5)

        painter.setPen(QColor(255, 255, 255, 255))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)
