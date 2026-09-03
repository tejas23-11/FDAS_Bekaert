"""
Orchestrates the backend and notification pipeline.
Owner: Member 3
"""

from __future__ import annotations
from cv.event import DetectedEvent
from backend.debounce import Debouncer, ActiveEventRegistry, process_new_detection
from backend.location import resolve_location, log_event
from backend.routing import get_route
from notify.sms_gateway import dispatch as dispatch_sms
from notify.voice_call import place_call

debouncer = Debouncer()
registry = ActiveEventRegistry()

def handle_detected_event(event: DetectedEvent):
    """
    Wires together debounce/dedupe -> location resolution + logging -> 
    routing -> notify -> resolution tracking.
    This is called by cv/capture.py's __main__ block for each detected event.
    """
    if not process_new_detection(event, debouncer, registry):
        return
        
    resolved_event = resolve_location(event)
    if not resolved_event:
        return
        
    log_event(resolved_event)
    
    route = get_route(resolved_event.message_type)
    
    if route.send_sms:
        dispatch_sms(
            db_record_id=resolved_event.db_record_id,
            device_code=resolved_event.device_code,
            message_type=resolved_event.message_type,
            location_name=resolved_event.location_name,
            contacts=resolved_event.contacts,
            dry_run=True  # Default to True for dry-run
        )
        
    if route.place_call and resolved_event.primary_contact:
        place_call(
            db_record_id=resolved_event.db_record_id,
            primary_contact=resolved_event.primary_contact,
            dry_run=True
        )
