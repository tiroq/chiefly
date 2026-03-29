from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/tasks"]


def find_oauth_credentials_file() -> Path:
    """
    Search for OAuth client credentials file:
    1. In the current script directory
    2. One level above the script directory

    Accepted names/patterns:
    - credentials.json
    - client_secret*.json
    - *.oauth.json
    """
    script_dir = Path(__file__).resolve().parent
    search_dirs = [script_dir, script_dir.parent]

    patterns = [
        "credentials.json",
        "client_secret*.json",
        "*.oauth.json",
    ]

    candidates: list[Path] = []

    for directory in search_dirs:
        for pattern in patterns:
            for path in directory.glob(pattern):
                if path.is_file():
                    candidates.append(path)

    # remove duplicates while preserving order
    unique_candidates: list[Path] = []
    seen = set()
    for path in candidates:
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique_candidates.append(path)

    if not unique_candidates:
        searched = "\n".join(str(d) for d in search_dirs)
        raise FileNotFoundError(
            "OAuth credentials file not found.\n"
            "Expected one of:\n"
            "  - credentials.json\n"
            "  - client_secret*.json\n"
            "  - *.oauth.json\n\n"
            f"Searched in:\n{searched}"
        )

    # Prefer credentials.json if present
    for candidate in unique_candidates:
        if candidate.name == "credentials.json":
            return candidate

    # Otherwise take first valid OAuth client file
    for candidate in unique_candidates:
        if is_valid_oauth_client_file(candidate):
            return candidate

    names = "\n".join(str(c) for c in unique_candidates)
    raise ValueError(
        "Found JSON files, but none look like OAuth client credentials.\n"
        f"Candidates:\n{names}"
    )


def is_valid_oauth_client_file(path: Path) -> bool:
    """
    Validate that file looks like an OAuth client secret JSON
    created for Desktop app or Web application.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False

    for root_key in ("installed", "web"):
        if root_key in data and isinstance(data[root_key], dict):
            block = data[root_key]
            required_keys = {"client_id", "client_secret", "auth_uri", "token_uri"}
            if required_keys.issubset(block.keys()):
                return True

    return False


def get_token_file_path(credentials_file: Path) -> Path:
    """
    Store token.json next to the script by default.
    """
    return Path(__file__).resolve().parent / "token.json"


def load_or_authorize() -> Credentials:
    credentials_file = find_oauth_credentials_file()
    token_file = get_token_file_path(credentials_file)

    print(f"Using OAuth credentials file: {credentials_file}")

    creds: Optional[Credentials] = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing existing token...")
            try:
                creds.refresh(Request())
            except Exception as exc:
                print(f"Token refresh failed ({exc}), starting fresh OAuth flow...")
                creds = None

        if not creds or not creds.valid:
            print("Opening browser for Google OAuth authorization...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_file),
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        token_file.write_text(creds.to_json(), encoding="utf-8")
        print(f"Saved token to: {token_file}")

    return creds


def main() -> None:
    creds = load_or_authorize()

    service = build("tasks", "v1", credentials=creds)
    results = service.tasklists().list(maxResults=50).execute()
    items = results.get("items", [])

    print("\nGoogle Tasks lists:")
    if not items:
        print("No task lists found.")
        return

    for item in items:
        print(f"- {item['title']} ({item['id']})")


if __name__ == "__main__":
    main()