"""Account-scoped exchange of short-lived WebRTC offers and answers."""
import json
from socket import gethostname
from uuid import UUID, uuid4

import httpx
from PySide6.QtCore import QObject, QRunnable, QSettings, QThreadPool, Signal, Slot

TABLE = "notcher_screen_invites"


def exchange(action, args, sender_id):
    from cloud.auth_service import get_current_session
    from cloud.bridge_service import make_client

    session = get_current_session()
    account = str(session.user.id) if session and session.user else None
    if action == "identity":
        return account
    if not account or account != args.get("account"):
        raise ValueError("Sign in to the same Notcher account on both devices.")

    with httpx.Client(timeout=5) as transport:
        client = make_client(session.access_token, transport)
        table = client.table(TABLE)
        if action == "list":
            return (
                table.select("id,device").eq("user_id", account)
                .neq("sender_id", sender_id).is_("answer", "null").gt("expires_at", "now")
                .order("expires_at", desc=True).limit(20).execute().data
            )
        if action == "offer":
            table.delete().eq("user_id", account).lte("expires_at", "now").execute()
            result = table.insert({
                "sender_id": sender_id,
                "device": gethostname()[:100] or "Notcher device",
                "offer": args["code"],
            }).execute()
            return result.data[0]["id"]

        invite = str(UUID(args["id"]))
        if action == "get":
            rows = (
                table.select("offer").eq("user_id", account).eq("id", invite)
                .neq("sender_id", sender_id).is_("answer", "null").gt("expires_at", "now")
                .execute().data
            )
            if rows:
                return rows[0]["offer"]
            raise ValueError("This invitation has expired, was cancelled, or was already accepted.")
        if action == "remove":
            table.delete().eq("user_id", account).eq("id", invite).eq("sender_id", sender_id).execute()
            return None
        if action == "poll":
            rows = (
                table.select("answer").eq("user_id", account).eq("id", invite)
                .eq("sender_id", sender_id).gt("expires_at", "now").execute().data
            )
            return rows[0] if rows else None
        if action == "answer":
            rows = (
                table.update({"answer": args["code"]}).eq("user_id", account)
                .eq("id", invite).neq("sender_id", sender_id).is_("answer", "null").gt("expires_at", "now")
                .execute().data
            )
            if not rows:
                raise ValueError("This invitation has expired, was cancelled, or was already accepted.")
            return None
    raise ValueError("Unknown screen sharing action.")


class ExchangeResult(QObject):
    ready = Signal(str, str)


class ExchangeWorker(QRunnable):
    def __init__(self, request_id, action, payload, sender_id):
        super().__init__()
        self.request_id, self.action, self.payload = request_id, action, payload
        self.sender_id = sender_id
        self.result = ExchangeResult()

    def run(self):
        try:
            data = exchange(self.action, json.loads(self.payload), self.sender_id)
            response = {"data": data}
        except ValueError as error:
            response = {"error": str(error)}
        except Exception:
            response = {"error": "Could not reach account sharing. Check your sign-in and connection."}
        self.result.ready.emit(self.request_id, json.dumps(response))


class AccountSignaling(QObject):
    reply = Signal(str, str)

    def __init__(self, parent):
        super().__init__(parent)
        settings = QSettings("Biosphir", "Notcher Share Screen")
        self.sender_id = settings.value("deviceId", "", type=str)
        if not self.sender_id:
            self.sender_id = str(uuid4())
            settings.setValue("deviceId", self.sender_id)

    @Slot(str, str, str)
    def send(self, request_id, action, payload):
        worker = ExchangeWorker(request_id, action, payload, self.sender_id)
        worker.result.ready.connect(self.reply)
        QThreadPool.globalInstance().start(worker)
