"""Short-lived WebRTC signaling for devices on one Notcher account."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from socket import gethostname
from uuid import UUID, uuid4

from PySide6.QtCore import QObject, Signal, Slot

TABLE = "notcher_screen_sessions"


class SignalingError(Exception):
    pass


class AccountSignaling(QObject):
    response = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix="share-screen")
        self._account = None
        self._closed = False
        self._offers = set()

    def _table(self):
        from cloud.auth_service import get_current_session
        from cloud.bridge_service import make_client

        session = get_current_session()
        if not session or not session.user or not session.access_token:
            raise SignalingError("Sign in to Notcher on both devices to share without codes.")
        owner = str(UUID(str(session.user.id)))
        if self._account is not None and owner != self._account:
            raise SignalingError("The account changed. Reopen Share Screen.")
        self._account = owner
        return make_client(session.access_token).table(TABLE)

    @staticmethod
    def _sdp(value):
        if not isinstance(value, str) or not value.startswith("v=0") or len(value) > 140000:
            raise SignalingError("The screen-sharing connection data is invalid.")
        return value

    def _execute(self, action, payload):
        table = self._table()
        now = datetime.now(timezone.utc).isoformat()
        if action == "list":
            return (table.select("id,device_name").eq("user_id", self._account)
                    .is_("answer", "null").gt("expires_at", now)
                    .order("created_at", desc=True).limit(30).execute().data)
        if action == "publish":
            table.delete().eq("user_id", self._account).lte("expires_at", now).execute()
            ident = str(uuid4())
            self._offers.add(ident)
            # Track the ID before the request in case the response is lost.
            table.insert({"id": ident, "user_id": self._account,
                          "device_name": gethostname()[:100] or "Notcher device",
                          "offer": self._sdp(payload.get("sdp"))}).execute()
            return ident
        if action not in {"offer", "answer", "response", "remove"}:
            raise SignalingError("Unknown screen-sharing action.")
        ident = str(UUID(payload["id"]))
        if action == "remove":
            if ident in self._offers:
                table.delete().eq("id", ident).eq("user_id", self._account).execute()
                self._offers.discard(ident)
            return None
        if action == "answer":
            rows = (table.update({"answer": self._sdp(payload.get("sdp"))}).eq("id", ident)
                    .eq("user_id", self._account).is_("answer", "null")
                    .gt("expires_at", now).select("id").execute().data)
            if not rows:
                raise SignalingError("This share has already been joined or has ended.")
            return None
        key = "offer" if action == "offer" else "answer"
        query = table.select(key).eq("id", ident).eq("user_id", self._account).gt("expires_at", now)
        if action == "offer":
            query = query.is_("answer", "null")
        rows = query.execute().data
        if not rows:
            raise SignalingError("This share has already been joined or has ended.")
        return rows[0][key]

    @Slot(str, str, str)
    def request(self, request_id, action, data):
        if not self._closed:
            self._workers.submit(self._reply, request_id, action, data)

    def _reply(self, request_id, action, data):
        try:
            payload = json.loads(data)
            result = {"value": self._execute(action, payload)}
        except SignalingError as error:
            result = {"error": str(error)}
        except Exception:
            result = {"error": "Account sharing is unavailable. Check your connection and try again."}
        try:
            self.response.emit(request_id, json.dumps(result))
        except RuntimeError:
            pass  # The window was closed while the request was running.

    def close(self):
        if self._closed:
            return
        self._closed = True

        def cleanup():
            for ident in tuple(self._offers):
                try:
                    self._execute("remove", {"id": ident})
                except Exception:
                    pass  # Unclaimed sessions expire automatically.

        self._workers.submit(cleanup)
        self._workers.shutdown(wait=False, cancel_futures=False)
