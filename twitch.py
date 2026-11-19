"""Busca os clipes mais vistos de um jogo na Twitch (Helix API) e baixa os escolhidos.

Credenciais: crie um app em https://dev.twitch.tv/console/apps (tipo "Confidential", redirect
http://localhost) e coloque client_id/client_secret em twitch_client.json.
A Twitch nao tem "curtidas" em clipes: o ranking e por visualizacoes (view_count).
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API = "https://api.twitch.tv/helix"


def _credenciais() -> tuple[str, str]:
    p = Path("twitch_client.json")
    c = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if not c.get("client_id") or not c.get("client_secret"):
        raise SystemExit("Preencha client_id e client_secret em twitch_client.json "
                         "(https://dev.twitch.tv/console/apps).")
    return c["client_id"], c["client_secret"]


def _headers() -> dict:
    cid, secret = _credenciais()
    r = requests.post("https://id.twitch.tv/oauth2/token", timeout=30, data={
        "client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
    if r.status_code != 200:
        raise SystemExit(f"Twitch recusou as credenciais: {r.text}")
    return {"Client-Id": cid, "Authorization": f"Bearer {r.json()['access_token']}"}


def achar_jogo(h: dict, nomes: list[str]) -> dict:
    for nome in nomes:
        r = requests.get(f"{API}/games", headers=h, params={"name": nome}, timeout=30)
        r.raise_for_status()
        if r.json()["data"]:
            return r.json()["data"][0]
    raise SystemExit(f"Categoria nao encontrada na Twitch (tentei {nomes}). "
                     "Ajuste twitch.jogo no config.yaml.")


def buscar(cfg: dict, ja_vistos: set[str]) -> list[dict]:
    """Os `quantidade` clipes mais vistos do ultimo dia, no idioma pedido, ainda nao usados."""
    t = cfg["twitch"]
    h = _headers()
    jogo = achar_jogo(h, t["jogo"])
    fim = datetime.now(timezone.utc)
    ini = fim - timedelta(hours=t.get("janela_horas", 24))
    idioma = t.get("idioma", "pt").lower()
    escolhidos, cursor = [], None
    for _ in range(15):   # ate 1500 clipes; a Twitch ja devolve ordenado por visualizacoes
        params = {"game_id": jogo["id"], "first": 100,
                  "started_at": ini.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "ended_at": fim.strftime("%Y-%m-%dT%H:%M:%SZ")}
        if cursor:
            params["after"] = cursor
        r = requests.get(f"{API}/clips", headers=h, params=params, timeout=30)
        r.raise_for_status()
        corpo = r.json()
        for c in corpo["data"]:
            if not c.get("language", "").lower().startswith(idioma):
                continue
            if c["id"] in ja_vistos or c.get("duration", 0) < t.get("duracao_min_seg", 0):
                continue
            escolhidos.append(c)
        cursor = corpo.get("pagination", {}).get("cursor")
        if len(escolhidos) >= t["quantidade"] or not cursor:
            break
    escolhidos.sort(key=lambda c: -c["view_count"])
    return escolhidos[:t["quantidade"]]


def baixar(clipe: dict, pasta: Path) -> Path:
    from yt_dlp import YoutubeDL
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{clipe['id']}.mp4"
    if destino.exists():
        return destino
    opts = {"outtmpl": str(pasta / f"{clipe['id']}.%(ext)s"), "quiet": True, "no_warnings": True, "noprogress": True,
            "format": "best[ext=mp4]/best", "merge_output_format": "mp4"}
    with YoutubeDL(opts) as y:
        y.download([clipe["url"]])
    if not destino.exists():
        achados = list(pasta.glob(f"{clipe['id']}.*"))
        if not achados:
            raise RuntimeError(f"download falhou: {clipe['url']}")
        return achados[0]
    return destino
