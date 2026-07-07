import os


def publish_post(payload: dict) -> dict:
    """Placeholder X connector.

    Production wiring should use OAuth 2.0 user context for posting. This adapter
    refuses execution until the required credentials and token storage are added.
    """
    if not os.getenv("X_CLIENT_ID") or not os.getenv("X_CLIENT_SECRET"):
        raise RuntimeError("X OAuth is not configured. Set X_CLIENT_ID and X_CLIENT_SECRET.")
    raise RuntimeError("X execution is scaffolded but not yet connected to stored user tokens.")
