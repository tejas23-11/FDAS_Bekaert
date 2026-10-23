import unittest
from unittest.mock import patch

from cv.ocr import _run_paddle_inference


class TestPaddleApiSelection(unittest.TestCase):

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
