from __future__ import annotations

import os

from .app import create_app
from .config import Config

config = Config.from_env()
app = create_app(config)

if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=config.debug,
        threaded=True,
    )
