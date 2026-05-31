"""Audio Normalizer – verlustfreie, dynamik-erhaltende Lautstärke-Normalisierung.

Das Paket ist bewusst in eine Qt-freie Kern-Engine (``engine``, ``batch``,
``measure``, ``probe``, ``ffmpeg_locator``, ``logwriter``) und eine dünne
GUI-Schicht (``gui``) getrennt. Dadurch ist die gesamte DSP-/FFmpeg-Logik
unabhängig vom UI test- und scriptbar (siehe ``cli``).
"""

__version__ = "2.0.0"
__app_name__ = "Audio Normalizer"

__all__ = ["__version__", "__app_name__"]
