from dataclasses import dataclass


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str = ""
    error: str = ""


class Provider:
    """Providers receive only what is needed to deliver: destination + content."""
    name = "base"

    def send(self, destination, body, subject=""):
        raise NotImplementedError
