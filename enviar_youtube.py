"""YouTube (API oficial): login e envio de um video.

Antes: projeto no Google Cloud com a YouTube Data API v3, credencial OAuth "Desktop app"
salva como client_secret.json. Login uma vez: python enviar_youtube.py login
Videos enviados por apps nao auditados ficam privados; peca a auditoria da API ou publique no
YouTube Studio. Cota gratuita: ~6 envios/dia.
"""
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

ESCOPO = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN = "token.json"


class CotaEsgotada(Exception):
    pass


def servico(interativo: bool = False):
    cred = None
    if Path(TOKEN).exists():
        cred = Credentials.from_authorized_user_file(TOKEN, ESCOPO)
        if not cred.valid:
            try:
                cred.refresh(Request()) if cred.expired and cred.refresh_token else None
            except Exception:
                cred = None
            if cred is not None and not cred.valid:
                cred = None
    if cred is None:
        if not interativo:
            raise SystemExit("YouTube sem login: rode 'python enviar_youtube.py login'")
        cred = InstalledAppFlow.from_client_secrets_file(
            "client_secret.json", ESCOPO).run_local_server(port=0)
    Path(TOKEN).write_text(cred.to_json())
    return build("youtube", "v3", credentials=cred)


def enviar(yt, video: Path, titulo: str, descricao: str, privacidade: str) -> str:
    corpo = {"snippet": {"title": titulo[:100], "description": descricao[:4900],
                         "categoryId": "20", "defaultLanguage": "pt",
                         "defaultAudioLanguage": "pt"},
             "status": {"privacyStatus": privacidade, "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=corpo,
                             media_body=MediaFileUpload(str(video), resumable=True))
    resp = None
    try:
        while resp is None:
            _, resp = req.next_chunk()
    except HttpError as e:
        if "quota" in str(e).lower():
            raise CotaEsgotada(str(e))
        raise
    return resp["id"]


if __name__ == "__main__":
    if sys.argv[1:] == ["login"]:
        Path(TOKEN).unlink(missing_ok=True)
        servico(interativo=True)
        print("Login OK.")
    else:
        print(__doc__)
