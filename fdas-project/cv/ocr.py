"""OCR engine — reads text from preprocessed panel screen images.

Primary engine: PaddleOCR (96%+ confidence on LCD panels)
Fallback: Tesseract (works but lower accuracy on blue LCD screens)

PaddleOCR uses the new .predict() API introduced in paddleocr v3.
Tesseract uses pytesseract with PSM 6 (uniform block of text).

Owner: Member 2.
"""

from __future__ import annotations

import numpy as np

# ── PaddleOCR (singleton) ─────────────────────────────────────────────
_paddle_engine = None
_paddle_import_failed = False


def _try_paddle_ocr(image: np.ndarray):
    """Try PaddleOCR on a numpy image (BGR or grayscale)."""
    global _paddle_engine, _paddle_import_failed
    if _paddle_import_failed:
        return None
    try:
        if _paddle_engine is None:
            from paddleocr import PaddleOCR

            _paddle_engine = PaddleOCR(
                lang="en",
                device="cpu",
                enable_mkldnn=False,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )

        # PaddleOCR v3 uses .predict() instead of .ocr()
        results = _paddle_engine.predict(input=image)

        all_texts = []
        all_scores = []
        for result in results:
            rec_texts = result.get("rec_texts", [])
            rec_scores = result.get("rec_scores", [])
            for t, s in zip(rec_texts, rec_scores):
                t_clean = str(t).strip()
                if t_clean:
                    all_texts.append(t_clean)
                    all_scores.append(float(s))

        if not all_texts:
            return "", 0.0

        text = " ".join(all_texts)
        confidence = sum(all_scores) / len(all_scores) if all_scores else 0.0
        return text, confidence

    except ImportError:
        _paddle_import_failed = True
        return None
    except Exception as e:
        print(f"[ocr] PaddleOCR failed, falling back to Tesseract: {e}")
        return None


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
