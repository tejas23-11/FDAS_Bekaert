"""OCR engine — reads text from preprocessed panel screen images.

Primary engine: RapidOCR (ONNX Runtime based; PP-OCR models with zero memory leaks)
Fallback: Tesseract (works but lower accuracy on blue LCD screens)

Tesseract uses pytesseract with PSM 6 (uniform block of text).

Owner: Member 2.
"""

from __future__ import annotations

from typing import Any
from pathlib import Path
import numpy as np

# ── RapidOCR (singleton) ──────────────────────────────────────────────
_rapid_engine = None
_rapid_import_failed = False


def _get_rapid_engine():
    """Lazy initialize and return singleton RapidOCR engine."""
    global _rapid_engine, _rapid_import_failed
    if _rapid_import_failed:
        return None
    if _rapid_engine is not None:
        return _rapid_engine
    try:
        from rapidocr_onnxruntime import RapidOCR
        _rapid_engine = RapidOCR()
        return _rapid_engine
    except Exception as e:
        _rapid_import_failed = True
        print(f"[ocr] RapidOCR import/init failed: {e}")
        return None


def _extract_rapid_texts(results: list | None) -> tuple[list[str], list[float]]:
    """Extract recognized texts and confidence scores from RapidOCR results."""
    texts = []
    scores = []
    if results:
        for item in results:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                t = str(item[1]).strip()
                if t:
                    texts.append(t)
                    try:
                        scores.append(float(item[2]))
                    except (ValueError, TypeError):
                        scores.append(0.9)
    return texts, scores


def _try_rapid_ocr(image: np.ndarray | str | Path) -> tuple[str, float] | None:
    """Try RapidOCR on a numpy image (BGR or grayscale) or image path."""
    engine = _get_rapid_engine()
    if engine is None:
        return None

    try:
        target = str(image) if hasattr(image, "__fspath__") or isinstance(image, Path) else image
        results, elapse = engine(target)
        if not results:
            return "", 0.0

        texts, scores = _extract_rapid_texts(results)
        if not texts:
            return "", 0.0

        text = " ".join(texts)
        confidence = sum(scores) / len(scores) if scores else 0.0
        return text, confidence
    except Exception as e:
        print(f"[ocr] RapidOCR inference failed: {e}")
        return None


# ── Backwards Compatibility Layer ─────────────────────────────────────
_paddle_engine = None
_paddle_import_failed = False
_arm_platform = None


def _is_arm_platform() -> bool:
    """Detect ARM architecture (Raspberry Pi, etc.). Kept for compatibility."""
    global _arm_platform
    if _arm_platform is None:
        import platform
        machine = platform.machine().lower()
        _arm_platform = machine.startswith("aarch64") or machine.startswith("arm")
    return _arm_platform


def _setup_arm_env():
    """Kept for backward compatibility."""
    pass


def _extract_paddlex_texts(res) -> tuple[list[str], list[float]]:
    """Extract recognized texts and scores from a PaddleX result object or dict."""
    texts = []
    scores = []
    data = None
    if hasattr(res, "json"):
        data = res.json
    elif isinstance(res, dict):
        data = res
    elif hasattr(res, "__dict__"):
        data = res.__dict__

    if isinstance(data, dict):
        sub = data.get("res", {}) if isinstance(data.get("res"), dict) else data
        rec_texts = data.get("rec_texts") or sub.get("rec_texts") or []
        rec_scores = data.get("rec_scores") or sub.get("rec_scores") or []
        for t, s in zip(rec_texts, rec_scores):
            t_clean = str(t).strip()
            if t_clean:
                texts.append(t_clean)
                try:
                    scores.append(float(s))
                except (ValueError, TypeError):
                    scores.append(0.9)
    return texts, scores


def _run_paddle_inference(engine: Any, image_path: str) -> tuple[str, Any]:
    """Compatibility runner for existing tests/callers."""
    if _is_arm_platform() and hasattr(engine, "ocr"):
        return "ocr", engine.ocr(image_path)
    if hasattr(engine, "predict"):
        return "predict", engine.predict(image_path)
    if hasattr(engine, "ocr"):
        return "ocr", engine.ocr(image_path)
    if callable(engine):
        res = engine(image_path)
        return "rapid", res[0] if isinstance(res, tuple) else res
    raise RuntimeError("OCR engine exposes neither predict(), ocr(), nor __call__")


def _try_paddle_ocr(image: np.ndarray):
    """Backward compatibility wrapper — routes directly to RapidOCR."""
    return _try_rapid_ocr(image)


# ── Tesseract fallback ────────────────────────────────────────────────

def _tesseract_ocr(image: np.ndarray):
    import pytesseract

    # PSM 6: "assume a uniform block of text" -- suited to a multi-line
    # panel display rather than the single-line PSM 7 used previously.
    config = "--psm 6"
    data = pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT)

    lines: dict[int, list[str]] = {}
    confidences = []
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        line_key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(line_key, []).append(word)
        conf = int(data["conf"][i])
        if conf >= 0:
            confidences.append(conf)

    text = "\n".join(" ".join(words) for words in lines.values()).strip()
    confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return text, confidence


def read_screen_text(preprocessed_image: np.ndarray):
    """
    Run OCR on the preprocessed screen ROI (output of cv/preprocess.py).

    Primary: RapidOCR (ONNX Runtime, fast, zero memory leaks).
    Fallback: Tesseract OCR.

    Returns:
        (text, confidence) -- text may be multi-line,
        confidence in [0, 1]. Returns ("", 0.0) on total failure so
        downstream classification naturally treats it as unreadable
        rather than needing its own error handling for this case.
    """
    ocr_result = _try_rapid_ocr(preprocessed_image)
    if ocr_result is not None:
        return ocr_result

    try:
        return _tesseract_ocr(preprocessed_image)
    except Exception as e:
        print(f"[ocr] Tesseract fallback failed: {e}")
        return "", 0.0
