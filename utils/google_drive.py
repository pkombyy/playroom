from __future__ import print_function
import io
import os
import pickle
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

def get_drive_service():
    creds = None
    token_path = "token.pickle"

    # Если уже авторизовались
    if os.path.exists(token_path):
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    # Если нет — запускаем поток авторизации
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            # ⬇️ без указания порта — он сам подберёт свободный и Google разрешит его
            creds = flow.run_local_server(port=0, open_browser=True)
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)

    return build("drive", "v3", credentials=creds)


def upload_to_drive(file_stream: io.BytesIO, filename: str) -> str:
    """Заливает файл в Google Drive и возвращает публичную ссылку."""
    service = get_drive_service()

    file_metadata = {"name": filename, "parents": ["root"]}
    media = MediaIoBaseUpload(file_stream, mimetype="application/zip", resumable=True)

    uploaded_file = service.files().create(
        body=file_metadata, media_body=media, fields="id"
    ).execute()

    service.permissions().create(
        fileId=uploaded_file["id"],
        body={"type": "anyone", "role": "reader"}
    ).execute()

    file_id = uploaded_file.get("id")
    return f"https://drive.google.com/uc?id={file_id}"
