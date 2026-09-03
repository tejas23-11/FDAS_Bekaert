import unittest
from backend.routing import get_route

class TestRouting(unittest.TestCase):
    def test_route_fire(self):
        route = get_route("fire")
        self.assertTrue(route.send_sms)
        self.assertTrue(route.place_call)

    def test_route_fault(self):
        route = get_route("fault")
        self.assertTrue(route.send_sms)
        self.assertFalse(route.place_call)

    def test_route_supervisory(self):
        route = get_route("supervisory")
        self.assertTrue(route.send_sms)
        self.assertFalse(route.place_call)

    def test_route_normal(self):
        route = get_route("normal")
        self.assertFalse(route.send_sms)
        self.assertFalse(route.place_call)

if __name__ == '__main__':
    unittest.main()
