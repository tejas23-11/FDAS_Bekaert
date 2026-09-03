"""
Routing configuration for the notification pipeline.
Owner: Member 3
"""

from __future__ import annotations
from dataclasses import dataclass

@dataclass
class RouteDecision:
    send_sms: bool
    place_call: bool

# Current routing rules
_ROUTES = {
    "fire": RouteDecision(send_sms=True, place_call=True),
    "fault": RouteDecision(send_sms=True, place_call=False),
    "supervisory": RouteDecision(send_sms=True, place_call=False),
    "normal": RouteDecision(send_sms=False, place_call=False),
    "unknown": RouteDecision(send_sms=False, place_call=False),
}

def get_route(message_type: str) -> RouteDecision:
    """
    Given a message_type, returns whether to send SMS and/or place a voice call.
    """
    return _ROUTES.get(message_type, RouteDecision(send_sms=False, place_call=False))
