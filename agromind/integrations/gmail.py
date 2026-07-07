import os


def send_draft(payload: dict) -> dict:
    """Placeholder Gmail connector.

    Production wiring should exchange the user's stored OAuth refresh token for an
    access token and call the Gmail API. This function intentionally refuses to
    send unless Gmail OAuth has been configured.
    """
    if not os.getenv("GOOGLE_CLIENT_ID") or not os.getenv("GOOGLE_CLIENT_SECRET"):
        raise RuntimeError("Gmail OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
    raise RuntimeError("Gmail OAuth execution is scaffolded but not yet connected to stored user tokens.")
