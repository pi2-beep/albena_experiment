import os

from wave2.web import create_app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("WAVE2_PORT", "5001")),
        debug=os.environ.get("WAVE2_DEBUG", "false").lower() == "true",
    )
