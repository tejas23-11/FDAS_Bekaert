"""OCR, now reading the full screen text block rather than one short code.

Tries PaddleOCR first (if installed), falls back to Tesseract. On the dev
machine right now only Tesseract is available -- that's expected and is
exactly why the fallback exists. Install paddleocr on the Pi for the real
deployment if you want the primary engine active; the fallback path is
fully functional on its own in the meantime.

Owner: Member 2.
"""

from __future__ import annotations

import numpy as np

_paddle_engine = None
_paddle_import_failed = False


def _try_paddle_ocr(image: np.ndarray):
    global _paddle_engine, _paddle_import_failed
    if _paddle_import_failed:
        return None
    try:
        if _paddle_engine is None:
            from paddleocr import PaddleOCR  # noqa: F401 (optional dependency)

            _paddle_engine = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)

        result = _paddle_engine.ocr(image, cls=False)
        if not result or not result[0]:
            return "", 0.0
        lines = [line[1][0] for line in result[0]]
        confidences = [line[1][1] for line in result[0]]
        text = "\n".join(lines).strip()
        confidence = float(sum(confidences) / len(confidences)) if confidences else 0.0
        return text, confidence
    except ImportError:
        _paddle_import_failed = True
        return None
    except Exception as e:  # pragma: no cover - defensive, engine-specific failures
        print(f"[ocr] PaddleOCR failed, falling back to Tesseract: {e}")
        return None


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

    Returns:
        (text, confidence) -- text may be multi-line (joined with \\n),
        confidence in [0, 1]. Returns ("", 0.0) on total failure so
        downstream classification naturally treats it as unreadable
        rather than needing its own error handling for this case.
    """
    paddle_result = _try_paddle_ocr(preprocessed_image)
    if paddle_result is not None:
        return paddle_result

    try:
        return _tesseract_ocr(preprocessed_image)
    except Exception as e:
        print(f"[ocr] Tesseract fallback failed: {e}")
        return "", 0.0
