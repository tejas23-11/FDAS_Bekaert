import unittest
import numpy as np
from cv.change_detect import screen_changed

class TestChangeDetect(unittest.TestCase):
    def test_first_frame(self):
        frame = np.ones((10, 10, 3), dtype=np.uint8)
        # Should be True because previous_frame is None
        self.assertTrue(screen_changed(frame, None, {"x": 0, "y": 0, "width": 10, "height": 10, "change_threshold": 5}))

    def test_no_change(self):
        frame1 = np.ones((10, 10, 3), dtype=np.uint8) * 10
        frame2 = np.ones((10, 10, 3), dtype=np.uint8) * 10
        self.assertFalse(screen_changed(frame2, frame1, {"x": 0, "y": 0, "width": 10, "height": 10, "change_threshold": 5}))

    def test_with_change(self):
        frame1 = np.ones((10, 10, 3), dtype=np.uint8) * 10
        frame2 = np.ones((10, 10, 3), dtype=np.uint8) * 20
        self.assertTrue(screen_changed(frame2, frame1, {"x": 0, "y": 0, "width": 10, "height": 10, "change_threshold": 5}))

if __name__ == '__main__':
    unittest.main()
