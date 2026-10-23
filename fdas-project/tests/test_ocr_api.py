import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from cv.ocr import (
    _run_paddle_inference,
    _extract_rapid_texts,
    _try_rapid_ocr,
    read_screen_text,
)


class TestRapidOcrApi(unittest.TestCase):

    def test_extract_rapid_texts(self):
        sample_results = [
            [[[0, 0], [10, 0], [10, 10], [0, 10]], "FIRE", "0.95"],
            [[[0, 10], [10, 10], [10, 20], [0, 20]], "L1 A053", 0.88],
            [[[0, 20], [10, 20], [10, 30], [0, 30]], "", 0.99],  # empty string should be ignored
        ]
        texts, scores = _extract_rapid_texts(sample_results)
        self.assertEqual(texts, ["FIRE", "L1 A053"])
        self.assertAlmostEqual(scores[0], 0.95)
        self.assertAlmostEqual(scores[1], 0.88)

    def test_try_rapid_ocr_mocked(self):
        mock_engine = MagicMock()
        mock_engine.return_value = (
            [
                [[[0, 0], [10, 0], [10, 10], [0, 10]], "Zone 1", 0.90],
                [[[0, 10], [10, 10], [10, 20], [0, 20]], "FIRE", 0.92],
            ],
            0.05,
        )
        with patch("cv.ocr._get_rapid_engine", return_value=mock_engine):
            dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
            text, conf = _try_rapid_ocr(dummy_img)

        self.assertEqual(text, "Zone 1 FIRE")
        self.assertAlmostEqual(conf, 0.91)

    def test_read_screen_text_fallback(self):
        with patch("cv.ocr._try_rapid_ocr", return_value=None):
            with patch("cv.ocr._tesseract_ocr", return_value=("TESS_TEXT", 0.75)):
                dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
                text, conf = read_screen_text(dummy_img)
                self.assertEqual(text, "TESS_TEXT")
                self.assertEqual(conf, 0.75)


class TestPaddleCompatibilityApiSelection(unittest.TestCase):

    def test_arm_prefers_legacy_ocr_api(self):
        class Engine:
            def __init__(self):
                self.called = None

            def ocr(self, image_path):
                self.called = "ocr"
                return ["legacy result"]

            def predict(self, image_path):
                self.called = "predict"
                return ["predict result"]

        engine = Engine()
        with patch("cv.ocr._is_arm_platform", return_value=True):
            api, results = _run_paddle_inference(engine, "panel.jpg")

        self.assertEqual(api, "ocr")
        self.assertEqual(results, ["legacy result"])
        self.assertEqual(engine.called, "ocr")

    def test_non_arm_prefers_predict_api(self):
        class Engine:
            def predict(self, image_path):
                return ["predict result"]

            def ocr(self, image_path):
                return ["legacy result"]

        with patch("cv.ocr._is_arm_platform", return_value=False):
            api, results = _run_paddle_inference(Engine(), "panel.jpg")

        self.assertEqual(api, "predict")
        self.assertEqual(results, ["predict result"])

    def test_ocr_only_engine_is_supported(self):
        class Engine:
            def ocr(self, image_path):
                return ["legacy result"]

        with patch("cv.ocr._is_arm_platform", return_value=False):
            api, results = _run_paddle_inference(Engine(), "panel.jpg")

        self.assertEqual(api, "ocr")
        self.assertEqual(results, ["legacy result"])


if __name__ == "__main__":
    unittest.main()
