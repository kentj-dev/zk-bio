from typing import Dict

class UserDirectory:
    @staticmethod
    def build_uid_to_name_map(conn) -> Dict[int, str]:
        uid_to_name: Dict[int, str] = {}
        for user in conn.get_users():
            name = (user.name or "").strip()
            if not name:
                name = (getattr(user, "user_id", "") or "").strip()
            if not name:
                name = f"UID {user.uid}"
            uid_to_name[user.uid] = name
        return uid_to_name
