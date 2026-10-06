import os

class Config:
    """
    Central place for app settings. Values are read from the environment
    (see .env.example) so nothing sensitive lives in source control.
    """

    DEBUG: bool = os.environ.get("DEBUG", os.environ.get("FLASK_DEBUG", "1")) == "1"
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://mercury_user:mercury_pass@localhost:5432/mercury",
    )

    # Allow the Deck.gl frontend (likely served from a different port/origin
    # during development, e.g. Vite on :5173) to call this API.
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.environ.get("CORS_ORIGINS", "*").split(",")
        if origin.strip()
    ]
