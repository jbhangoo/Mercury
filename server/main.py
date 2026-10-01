"""ASGI application and local development entry point for the Mercury API."""

from pathlib import Path

import uvicorn

from dotenv import load_dotenv

load_dotenv()

from app import create_app

app = create_app()


if __name__ == "__main__":
	uvicorn.run(
		"main:app",
		app_dir=str(Path(__file__).resolve().parent),
		host="0.0.0.0",
		port=8000,
		reload=True,
	)