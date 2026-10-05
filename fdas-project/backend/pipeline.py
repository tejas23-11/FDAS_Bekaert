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

def handle_detected_event(event: DetectedEvent, dry_run: bool = True, skip_debounce: bool = False):
    """
    Wires together debounce/dedupe -> location resolution + logging -> 
    routing -> notify -> resolution tracking.

    Args:
        event: The detected event from the CV pipeline.
        dry_run: If True, print notifications instead of sending real SMS/calls.
        skip_debounce: If True, bypass debounce + dedupe (used by run_live.py
                       for single-image processing where multi-frame
                       confirmation is not applicable).
    """
    if not skip_debounce:
        if not process_new_detection(event, debouncer, registry):
            return

    resolved_event = resolve_location(event)
    if not resolved_event:
        if event.message_type == "fire":
            # Real fire alert: do not drop notification even if unmapped in device_map
            from backend.location import _get_global_contacts
            from cv.event import ResolvedEvent
            global_sms = _get_global_contacts("sms") or ["+919545202660"]
            global_call = _get_global_contacts("call")
            primary = global_call[0] if global_call else global_sms[0]
            resolved_event = ResolvedEvent(
                device_code=event.device_code,
                message_type=event.message_type,
                raw_text=event.raw_text,
                timestamp=event.timestamp,
                confidence=event.confidence,
                frame_id=event.frame_id,
                location_name="Unknown location",
                zone="Unknown zone",
                device_type="Unknown",
                contacts=global_sms,
                primary_contact=primary,
            )
        else:
            print(f"  [!!] Location resolve FAILED for device '{event.device_code}' — not in device_map")
            return
        
    log_event(resolved_event)
    print(f"  [OK] Event logged to DB (id={resolved_event.db_record_id})")
    
    route = get_route(resolved_event.message_type)
    print(f"  [OK] Route: send_sms={route.send_sms}, place_call={route.place_call}")
    
    if route.send_sms:
        dispatch_sms(
            db_record_id=resolved_event.db_record_id,
            device_code=resolved_event.device_code,
            message_type=resolved_event.message_type,
            location_name=resolved_event.location_name,
            contacts=resolved_event.contacts,
            device_type=resolved_event.device_type,
            zone=resolved_event.zone,
            dry_run=dry_run,
            raw_text=resolved_event.raw_text,
        )
        
    if route.place_call and resolved_event.primary_contact:
        place_call(
            db_record_id=resolved_event.db_record_id,
            primary_contact=resolved_event.primary_contact,
            dry_run=dry_run,
        )
