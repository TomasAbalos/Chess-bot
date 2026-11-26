<div align="center">

<img src="assets/icon.png" alt="Chess Assistant Logo" width="160" height="160" style="margin-bottom: 12px;" />

# ♟️ Chess Assistant & Overlay Bot

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://riverbankcomputing.com/software/pyqt/)
[![OpenCV](https://img.shields.io/badge/Vision-OpenCV%20%2B%20ONNX-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white)](https://opencv.org/)
[![Stockfish](https://img.shields.io/badge/Engine-Stockfish%20UCI-000000?style=for-the-badge&logo=lichess&logoColor=white)](https://stockfishchess.org/)
[![Multiplatform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-informational?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/TomasAbalos/Chess-bot)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

**Un asistente visual moderno para ajedrez en pantalla con visión computacional, overlay transparente en tiempo real y cálculo mediante motor Stockfish.**

*Compatible con **Windows** y **macOS** — Adaptado por **Tomás Ábalos***

---

</div>

## ⚠️ Disclaimer & Uso Ético (Descargo de Responsabilidad)

> [!CAUTION]
> **PROYECTO CREADO EXCLUSIVAMENTE CON FINES EDUCATIVOS Y DE ENTRETENIMIENTO.**
>
> Este software fue desarrollado para explorar visión artificial (detección de tableros con transformadas de Hough y clasificación de piezas por redes neuronales convolucionales), automatización y desarrollo de interfaces con PyQt6.
> 
> **NO debe utilizarse para hacer trampas ni para obtener ventajas injustas** en partidas en línea contra jugadores reales (en plataformas como Lichess, Chess.com o similares). El uso de asistencia computacional en partidas competitivas viola los términos de servicio de dichas plataformas y perjudica a la comunidad. Úsalo con responsabilidad frente a bots, en partidas de análisis o en entornos offline.

---

## ✨ Características Principales

- 🖥️ **Overlay Transparente Click-Through**: Muestra flechas visuales y casillas iluminadas indicando la mejor jugada sin interferir con tus clics ni bloquear tu visión.
- 👁️ **Detección Automática de Tablero**: Localiza el tablero en tu monitor usando visión por computadora sin configuración manual de coordenadas.
- 🧠 **Red Neuronal ONNX**: Clasifica las 64 casillas del tablero en milisegundos para sincronizar la posición FEN exacta.
- 🎯 **Sugerencia Instantánea**: Integración con Stockfish para calcular respuestas óptimas con tiempo y profundidad configurables.
- 🍏 **Soporte Multiplataforma**: Captura nativa ultra rápida con **DXCam** en Windows y **MSS / CoreGraphics** en macOS.

---

## 📥 Instalación del Motor Stockfish

El asistente necesita el motor **Stockfish** para evaluar las posiciones. Instálalo según tu sistema operativo:

### 🍎 En macOS (Recomendado vía Homebrew)
Si tienes [Homebrew](https://brew.sh/) instalado, es un solo comando:
```bash
brew install stockfish
```
*(El programa lo detectará automáticamente en `/opt/homebrew/bin/stockfish` o `/usr/local/bin/stockfish`).*

### 🪟 En Windows
**Opción A (Rápida con Winget):**
```powershell
winget install Stockfish.Stockfish
```
**Opción B (Manual):**
1. Descarga el ejecutable oficial desde [stockfishchess.org/download](https://stockfishchess.org/download/).
2. Extrae el archivo `stockfish.exe` en tu Escritorio dentro de una carpeta llamada `stockfish` (o selecciónalo directamente desde la pestaña **Motor Stockfish** en el programa).

---

## 🚀 Instalación y Puesta en Marcha

### 1. Clonar el repositorio
```bash
git clone https://github.com/TomasAbalos/Chess-bot.git
cd Chess-bot
```

### 2. Configurar el entorno de Python

#### 🪟 En Windows:
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[windows]"
```

#### 🍎 En macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

> [!NOTE]
> **Permisos en macOS**: La primera vez que lo ejecutes en Mac, el sistema te solicitará conceder permisos de **Grabación de Pantalla** y **Accesibilidad** a tu terminal o a Python en:
> *Ajustes del Sistema → Privacidad y Seguridad → Grabación de pantalla y audio del sistema*.

---

## 🎮 Cómo Ejecutar

### Opción 1: Interfaz Gráfica (Recomendado)
```bash
python run_chessbot.py
```
*(En Windows también puedes hacer doble clic en `Iniciar_ChessAssistant.bat`).*

### Opción 2: Modo Consola (CLI)
```bash
# Modo asistente visual
chessbot gui

# Modo por terminal clásico
chessbot play --engine stockfish
```

---

## 🛠️ Tecnologías Utilizadas

- **Python**: Lenguaje base del proyecto.
- **PyQt6**: Interfaz gráfica y overlay HUD flotante.
- **OpenCV, DXCam & MSS**: Captura y procesamiento visual de pantalla de ultra baja latencia.
- **Python-Chess**: Validación reglamentaria, parsing de FEN y comunicación UCI con el motor.
- **ONNX Runtime / OpenCV DNN**: Inferencia rápida de piezas sin necesidad de frameworks pesados de IA.

---

## 👤 Autor & Créditos

- **Adaptación, Interfaz Gráfica y Overlay:** [Tomás Ábalos](https://github.com/TomasAbalos)
- Basado en el proyecto original [OpenCV-Chess-Bot](https://github.com/7dpk/OpenCV-Chess-Bot) de **7dpk**.

<div align="center">
  <sub>Proyecto creado con fines educativos y de aprendizaje.</sub>
</div>
