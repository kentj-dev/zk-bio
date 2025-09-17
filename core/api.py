import json
from dataclasses import asdict
from typing import List, Callable
from zk_bio.core.parsing import ParsedAttendance

class ApiGround:
    """
    Pluggable API surface. Currently prints and returns True.
    Swap this with real requests in the future.
    """
    def __init__(self, emit_log: Callable[[str, str], None]):
        self.emit_log = emit_log

    def send_batch(self, batch: List[ParsedAttendance]) -> bool:
        payload = [asdict(item) for item in batch]
        self.emit_log("api", f"Sending {len(payload)} stamps...")
        self.emit_log("api", f"Payload: {json.dumps(payload, ensure_ascii=False)}")
        return True

    def send_one(self, item: ParsedAttendance) -> bool:
        return self.send_batch([item])
