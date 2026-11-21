"""Request the controlled systemd restart after changing runtime settings."""

import os
import signal


def request_service_restart() -> None:
    """Stop the current service process after its HTTP response is sent.

    The packaged systemd units use ``Restart=always``.  SIGTERM consequently
    lets uvicorn shut down cleanly and starts the service again with the new
    optional runtime environment file.

    Returns:
        None.
    """
    os.kill(os.getpid(), signal.SIGTERM)
