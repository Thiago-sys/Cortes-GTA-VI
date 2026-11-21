"""Busca os clipes mais vistos de um jogo na Kick e baixa os escolhidos.

A Kick nao tem API oficial de clipes; usa-se a API publica do site (sem login/credenciais).
O clipe da Kick nao informa o idioma, entao ele e resolvido pelo canal: idioma da live atual
ou, se o canal estiver offline, o do VOD mais recente. O resultado fica em kick_canais.json
(cache) para nao repetir a consulta. Os clipes saem no mesmo formato dos da Twitch.
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API = "https://kick.com/api"
CACHE = Path("kick_canais.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "application/json"}
# nome do idioma na Kick -> prefixo aceito em config (pt, en, es...)
IDIOMAS = {"portuguese": "pt", "english": "en", "spanish": "es", "french": "fr", "german": "de",
           "italian": "it", "russian": "ru", "turkish": "tr", "japanese": "ja", "korean": "ko"}


def _get(url: str, **params) -> dict | list | None:
    """GET com poucas tentativas; None se o recurso nao existe ou segue falhando."""
    for tentativa in range(3):
        try:
            r = requests.get(url, headers=HEADERS, params=params or None, timeout=30)
        except requests.RequestException:
            r = None
        if r is not None and r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                return None
        if r is not None and r.status_code == 404:
            return None
        time.sleep(2 * (tentativa + 1))
    return None


def achar_categoria(nomes: list[str]) -> dict:
    for nome in nomes:
        d = _get(f"{API}/search", searched_word=nome)
        for c in (d or {}).get("categories", []):
            # aceita pelo slug exato ("grand-theft-auto-vi") ou pelo nome da categoria
            if c["slug"] == nome or c["name"].lower().startswith(nome.lower()):
                return c
    raise SystemExit(f"Categoria nao encontrada na Kick (tentei {nomes}). Ajuste kick.jogo no config.yaml.")


def _cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def idioma_do_canal(slug: str, cache: dict, validade_dias: int = 30) -> str:
    """Prefixo do idioma do canal ('pt', 'en'...) ou '' se nao deu para saber."""
    e = cache.get(slug)
    if e and e.get("idioma") is not None and \
            time.time() - e.get("quando", 0) < validade_dias * 86400:
        return e["idioma"]
    nome = None
    canal = _get(f"{API}/v2/channels/{slug}")
    if isinstance(canal, dict) and isinstance(canal.get("livestream"), dict):
        nome = canal["livestream"].get("language")
    if not nome:
        videos = _get(f"{API}/v2/channels/{slug}/videos")
        videos = videos if isinstance(videos, list) else (videos or {}).get("data", [])
        # VOD mais recente que tenha idioma
        nome = next((v["language"] for v in videos if v.get("language")), None)
    if not nome:
        return ""      # nao salva: tenta de novo na proxima execucao
    idioma = IDIOMAS.get(nome.lower(), nome.lower()[:2])
    cache[slug] = {"idioma": idioma, "quando": time.time()}
    return idioma


def _data(texto: str) -> datetime | None:
    """ISO da Kick ('2026-11-20T13:53:50.83514Z'); descarta a fracao, que o Python 3.10 nao le."""
    try:
        return datetime.strptime(texto[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _normalizar(c: dict) -> dict:
    canal = c.get("channel") or {}
    slug = canal.get("slug", "")
    return {"id": f"kick_{c['id']}", "fonte": "kick", "title": (c.get("title") or "").strip(),
            "broadcaster_name": canal.get("username") or slug, "canal_slug": slug,
            "url": f"https://kick.com/{slug}/clips/{c['id']}", "video_url": c.get("video_url") or c.get("clip_url"),
            "view_count": c.get("view_count", c.get("views", 0)), "duration": c.get("duration", 0),
            "created_at": c.get("created_at", "")}


def buscar(cfg: dict, ja_vistos: set[str]) -> list[dict]:
    """Os `quantidade` clipes mais vistos do ultimo dia, de canais no idioma pedido, ainda nao usados."""
    k = cfg["kick"]
    cat = achar_categoria(k["jogo"])
    idioma = k.get("idioma", "pt").lower()
    horas = k.get("janela_horas", 24)
    # ate 24 h vale a janela "day" da Kick (que ja decide o que e "o dia"); acima disso filtra aqui
    corte = datetime.now(timezone.utc) - timedelta(hours=horas) if horas > 24 else None
    bloqueados = {s.lower() for s in k.get("canais_ignorar", [])}
    cache = _cache()
    candidatos, cursor = [], None
    for _ in range(10):   # a Kick ja devolve ordenado por visualizacoes (20 por pagina)
        params = {"sort": "view", "time": "day" if horas <= 24 else "week"}
        if cursor:
            params["cursor"] = cursor
        corpo = _get(f"{API}/v2/categories/{cat['slug']}/clips", **params)
        if not corpo or not corpo.get("clips"):
            break
        for bruto in corpo["clips"]:
            c = _normalizar(bruto)
            criado = _data(c["created_at"])
            if (corte and criado and criado < corte) or c["id"] in ja_vistos or not c["canal_slug"] \
                    or c["canal_slug"].lower() in bloqueados or c["duration"] < k.get("duracao_min_seg", 0) \
                    or bruto.get("privacy", "public") != "public":
                continue
            candidatos.append(c)
        cursor = corpo.get("nextCursor")
        if not cursor:
            break
    candidatos.sort(key=lambda c: -c["view_count"])
    escolhidos = []
    for c in candidatos:   # so consulta o idioma dos canais necessarios, do mais visto para o menos
        if idioma_do_canal(c["canal_slug"], cache).startswith(idioma):
            escolhidos.append(c)
            if len(escolhidos) >= k["quantidade"]:
                break
    try:
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return escolhidos


def baixar(clipe: dict, pasta: Path) -> Path:
    from yt_dlp import YoutubeDL
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{clipe['id']}.mp4"
    if destino.exists():
        return destino
    opts = {"outtmpl": str(pasta / f"{clipe['id']}.%(ext)s"), "quiet": True, "no_warnings": True,
            "noprogress": True, "format": "best", "merge_output_format": "mp4"}
    with YoutubeDL(opts) as y:
        y.download([clipe["video_url"]])
    achados = list(pasta.glob(f"{clipe['id']}.*"))
    if not achados:
        raise RuntimeError(f"download falhou: {clipe['url']}")
    return destino if destino.exists() else achados[0]
