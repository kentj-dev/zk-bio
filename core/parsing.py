import re
from dataclasses import dataclass
from typing import Optional, Dict
from zk_bio.constants import TIME_PHASE_MAP, MODE_MAP

@dataclass
class ParsedAttendance:
    biometric_id: int
    date: str          # YYYY-MM-DD
    time: str          # HH:MM:SS
    mode_of_attendance: int
    time_phase: int

class AttendanceParser:
    ATTENDANCE_RE = re.compile(
        r"^<Attendance>:\s*(?P<uid>\d+)\s*:\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s*\(\s*(?P<mode>\d+)\s*,\s*(?P<phase>\d+)\s*\)\s*$"
    )

    @staticmethod
    def parse_text(raw: str) -> Optional[ParsedAttendance]:
        m = AttendanceParser.ATTENDANCE_RE.match(raw.strip())
        if not m:
            return None
        return ParsedAttendance(
            biometric_id=int(m.group("uid")),
            date=m.group("date"),
            time=m.group("time"),
            mode_of_attendance=int(m.group("mode")),
            time_phase=int(m.group("phase")),
        )

    @staticmethod
    def parse_object(attendance_obj) -> Optional[ParsedAttendance]:
        try:
            uid = int(getattr(attendance_obj, "user_id", getattr(attendance_obj, "uid")))
            ts = getattr(attendance_obj, "timestamp")
            mode = int(getattr(attendance_obj, "status", getattr(attendance_obj, "mode", -1)))
            phase = int(getattr(attendance_obj, "punch", getattr(attendance_obj, "time_phase", -1)))
            date = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts).split(" ")[0]
            time_s = ts.strftime("%H:%M:%S") if hasattr(ts, "strftime") else str(ts).split(" ")[1]
            return ParsedAttendance(uid, date, time_s, mode, phase)
        except Exception:
            return None

    @staticmethod
    def phase_text(phase: int) -> str:
        return TIME_PHASE_MAP.get(phase, f"phase {phase}")

    @staticmethod
    def mode_text(mode: int) -> str:
        return MODE_MAP.get(mode, f"mode {mode}")

    @staticmethod
    def punch_display(parsed: ParsedAttendance, name_lookup: Dict[int, str]) -> str:
        name = name_lookup.get(parsed.biometric_id, "Unknown User")
        return (
            f"[{name}] ({parsed.biometric_id}) - {parsed.date} at {parsed.time} - "
            f"{AttendanceParser.mode_text(parsed.mode_of_attendance)} - {AttendanceParser.phase_text(parsed.time_phase)}"
        )

    @staticmethod
    def queue_display(parsed: ParsedAttendance, name_lookup: Dict[int, str]) -> str:
        name = name_lookup.get(parsed.biometric_id, "Unknown User")
        return (
            f"[{name}] ({parsed.biometric_id}) - {parsed.date} {parsed.time} - "
            f"{AttendanceParser.mode_text(parsed.mode_of_attendance)} - {AttendanceParser.phase_text(parsed.time_phase)}"
        )
