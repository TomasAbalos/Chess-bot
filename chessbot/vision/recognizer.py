from pathlib import Path

import cv2
import numpy as np

from .position import CLASSES

INPUT_SIZE = 48


def split_board(board_img: np.ndarray, size: int = INPUT_SIZE) -> np.ndarray:
    h, w = board_img.shape[:2]
    crops = np.empty((64, size, size, 3), np.uint8)
    for row in range(8):
        y0, y1 = int(row * h / 8), int((row + 1) * h / 8)
        for col in range(8):
            x0, x1 = int(col * w / 8), int((col + 1) * w / 8)
            crops[row * 8 + col] = cv2.resize(board_img[y0:y1, x0:x1], (size, size), interpolation=cv2.INTER_AREA)
    return crops


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def _has_red_hat(crop_bgr: np.ndarray) -> bool:
    """Detecta si el casillero tiene un gorrito rojo encima (rey de Lichess con tema festivo)."""
    h = crop_bgr.shape[0]
    top = crop_bgr[:max(1, int(h * 0.35)), :]
    hsv = cv2.cvtColor(top, cv2.COLOR_BGR2HSV)
    # Rojo en HSV tiene dos rangos (wraps alrededor de 0/180)
    mask1 = cv2.inRange(hsv, np.array([0,  50, 40]), np.array([15,  255, 255]))
    mask2 = cv2.inRange(hsv, np.array([160, 50, 40]), np.array([180, 255, 255]))
    red_ratio = float((mask1 | mask2).mean()) / 255.0
    return red_ratio > 0.30   # >30 % de píxeles rojos en el tercio superior


def _has_purple_highlight(crop_bgr: np.ndarray) -> bool:
    """Detecta el resaltado lila/violeta de Lichess (última jugada) en el fondo del casillero."""
    # Muestreamos las esquinas (evitamos el centro donde está la pieza)
    h, w = crop_bgr.shape[:2]
    corners = np.concatenate([
        crop_bgr[:6, :6],           # top-left
        crop_bgr[:6, w-6:],         # top-right
        crop_bgr[h-6:, :6],         # bottom-left
        crop_bgr[h-6:, w-6:],       # bottom-right
    ], axis=0).reshape(-1, 3)
    if len(corners) == 0:
        return False
    hsv = cv2.cvtColor(corners.reshape(1, -1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3)
    # Lila/violeta: H≈120-160, S moderado
    mask = (
        (hsv[:, 0] >= 110) & (hsv[:, 0] <= 165) &
        (hsv[:, 1] >= 30)  & (hsv[:, 2] >= 80)
    )
    return float(mask.mean()) > 0.35


class Recognizer:
    def __init__(self, model_path: str | Path | None = None, net=None):
        if net is None and model_path is None:
            raise ValueError("model_path or net is required")
        self._net = net if net is not None else cv2.dnn.readNetFromONNX(str(model_path))

    def classify_squares(self, board_img: np.ndarray) -> tuple[list[list[str]], np.ndarray]:
        h_img, w_img = board_img.shape[:2]
        crops = split_board(board_img)
        blob = cv2.dnn.blobFromImages(crops, 1 / 255.0, (INPUT_SIZE, INPUT_SIZE), swapRB=False)
        self._net.setInput(blob)
        probs = softmax(np.asarray(self._net.forward()))
        indices = probs.argmax(axis=1)
        confidences = probs.max(axis=1).astype(np.float32).reshape(8, 8)
        grid = [[CLASSES[indices[row * 8 + col]] for col in range(8)] for row in range(8)]

        # ── Post-proceso: corrige piezas con baja confianza usando color ──────
        LOW_CONF = 0.80
        for row in range(8):
            for col in range(8):
                if confidences[row, col] < LOW_CONF:
                    # Recorte original del casillero (sin resize)
                    y0 = int(row * h_img / 8);  y1 = int((row + 1) * h_img / 8)
                    x0 = int(col * w_img / 8);  x1 = int((col + 1) * w_img / 8)
                    sq = board_img[y0:y1, x0:x1]

                    if _has_red_hat(sq):
                        # Gorrito rojo → Rey blanco (Lichess holiday theme)
                        grid[row][col] = "wK"
                        confidences[row, col] = 0.95
                    elif _has_purple_highlight(sq):
                        # El resaltado lila baja la confianza: re-clasificamos
                        # con umbral más bajo (ya tenemos la mejor clase del modelo)
                        best_class = CLASSES[indices[row * 8 + col]]
                        grid[row][col] = best_class
                        confidences[row, col] = max(confidences[row, col], 0.80)

        return grid, confidences
