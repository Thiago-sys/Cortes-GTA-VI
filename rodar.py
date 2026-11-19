"""Rotina diaria: busca os clipes mais vistos de GTA 6 (pt) na Twitch, edita via Gemini e publica.

Uso:
  python rodar.py                 rotina completa
  python rodar.py --sem-publicar  baixa e edita, mas nao envia (confira em prontos/)
  python rodar.py --sem-gemini    edita sem o Gemini (sem previa/legenda; titulo = o do clipe)
  python rodar.py --so-publicar   nao busca nem edita: so envia o que ja esta em prontos/ e pendente
Os envios que falharam (cota, rede) sao retomados na execucao seguinte.
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

import twitch
from editar import duracao_video, editar, versao_leve
from gemini import Gemini, GeminiErro, GeminiSemLogin

# erros do TikTok que valem para a conta toda (os demais so afetam aquele video)
PARAR_TIKTOK = ("rate_limit", "spam_risk", "too_many", "access_token", "scope_not_authorized",
                "user_banned", "sem login")
HISTORICO = Path("historico.json")
PRONTOS = Path("prontos")
TRABALHO = Path("trabalho")


def log(msg: str) -> None:
    linha = f"[{datetime.now():%d/%m %H:%M:%S}] {msg}"
    print(linha, flush=True)
    with open("log.txt", "a", encoding="utf-8") as f:
        f.write(linha + "\n")


def carregar_historico() -> dict:
    """Le o historico; se estiver vazio/corrompido, guarda uma copia e recomeca em vez de travar."""
    if not HISTORICO.exists():
        return {}
    texto = HISTORICO.read_text(encoding="utf-8").strip()
    if not texto:
        return {}
    try:
        h = json.loads(texto)
        if isinstance(h, dict):
            return h
    except json.JSONDecodeError:
        pass
    copia = HISTORICO.with_suffix(".json.corrompido")
    shutil.copy(HISTORICO, copia)
    log(f"historico.json invalido; copia salva em {copia.name} e comecando um novo")
    return {}


def salvar_historico(h: dict) -> None:
    """Grava em arquivo temporario e troca (atomico): uma queda no meio nao corrompe o historico."""
    tmp = HISTORICO.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(HISTORICO)


def montar_textos(clipe: dict, plano: dict | None, cfg: dict) -> tuple[str, str, list[str]]:
    plano = plano or {}
    titulo = (plano.get("titulo") or clipe["title"]).strip()
    tags = []
    for t in cfg["publicacao"]["hashtags"] + plano.get("hashtags", []):
        if t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    corpo = [plano.get("descricao") or "", f"Clipe de {clipe['broadcaster_name']} na Twitch: {clipe['url']}",
             " ".join(tags)]
    return titulo, "\n\n".join(p for p in corpo if p), tags


def publicar(h: dict, cfg: dict, enviados: dict) -> None:
    """Envia ao YouTube/TikTok o que ainda falta de cada corte pronto (ordem: mais vistos primeiro)."""
    pub = cfg["publicacao"]
    pend = sorted((e for e in h.values() if e.get("arquivo") and Path(e["arquivo"]).exists()),
                  key=lambda e: -e.get("views", 0))
    yt = None
    for e in pend:
        video = Path(e["arquivo"])
        if pub.get("youtube") and not e.get("youtube_id") \
                and enviados["yt"] < pub.get("max_youtube_por_dia", 5):
            try:
                import enviar_youtube as y
                yt = yt or y.servico()
                e["youtube_id"] = y.enviar(yt, video, e["titulo"], e["descricao"],
                                           pub.get("privacidade_youtube", "private"))
                enviados["yt"] += 1
                log(f"YouTube OK: {e['titulo']} -> https://youtu.be/{e['youtube_id']}")
            except Exception as ex:   # inclui SystemExit (sem login) e cota
                log(f"YouTube falhou ({e['id']}): {str(ex)[:200]}")
                if ex.__class__.__name__ in ("CotaEsgotada", "SystemExit"):
                    enviados["yt"] = 10**6   # nao insiste nos demais
        if pub.get("tiktok") and not e.get("tiktok_id") and not enviados.get("tt_parou")                 and enviados.get("tt", 0) < pub.get("max_tiktok_por_dia", 5):
            try:
                import enviar_tiktok as t
                tags = " ".join(e["hashtags"])
                e["tiktok_id"] = t.enviar(video, f"{e['titulo'][:150 - len(tags) - 1]} {tags}")
                enviados["tt"] = enviados.get("tt", 0) + 1
                log(f"TikTok OK (rascunho na caixa de entrada): {e['titulo']}")
            except (Exception, SystemExit) as ex:
                log(f"TikTok falhou ({e['id']}): {str(ex)[:200]}")
                if "too_many_pending" in str(ex):
                    log("TikTok: limite de rascunhos pendentes (~5). Abra o app, publique ou "
                        "descarte os rascunhos da caixa de entrada e rode de novo; os demais "
                        "videos ficam para a proxima execucao.")
                if any(k in str(ex) for k in PARAR_TIKTOK):
                    enviados["tt_parou"] = True   # limite/login: tenta de novo na proxima execucao
        salvar_historico(h)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # titulos com emoji
    args = sys.argv[1:]
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    h = carregar_historico()
    enviados = {"yt": 0}

    if "--so-publicar" in args:
        pend = [e for e in h.values() if e.get("arquivo") and Path(e["arquivo"]).exists()
                and ((cfg["publicacao"].get("youtube") and not e.get("youtube_id"))
                     or (cfg["publicacao"].get("tiktok") and not e.get("tiktok_id")))]
        log(f"Somente publicar: {len(pend)} video(s) pendente(s) em prontos/")
        publicar(h, cfg, enviados)
        log("Fim.")
        return

    novos = twitch.buscar(cfg, set(h))
    log(f"{len(novos)} clipe(s) novo(s) de GTA 6 em {cfg['twitch']['idioma']}")

    gem = None
    if novos and "--sem-gemini" not in args:
        try:
            gem = Gemini(cfg).__enter__()
        except Exception as ex:
            log(f"Gemini indisponivel ({ex}); editando sem ele")
    try:
        for c in novos:
            try:
                bruto = twitch.baixar(c, TRABALHO)
                dur = duracao_video(bruto)
                plano = None
                if gem:
                    try:
                        plano = gem.analisar(versao_leve(bruto, TRABALHO / 'leve' / bruto.name), c, dur)
                    except GeminiSemLogin:
                        log("Gemini sem login (rode: python gemini.py login); editando sem ele")
                        gem.__exit__(None, None, None)
                        gem = None
                    except GeminiErro as ex:
                        log(f"Gemini falhou em {c['id']}: {str(ex)[:150]}; editando sem previa/legenda")
                titulo, descricao, tags = montar_textos(c, plano, cfg)
                saida = editar(bruto, PRONTOS / f"{c['id']}.mp4",
                               plano or {"previa": None, "legendas": []}, cfg)
                h[c["id"]] = {"id": c["id"], "arquivo": str(saida), "titulo": titulo,
                              "descricao": descricao, "hashtags": tags, "views": c["view_count"],
                              "streamer": c["broadcaster_name"], "url": c["url"],
                              "gemini": plano is not None,
                              "data": datetime.now().isoformat(timespec="seconds")}
                salvar_historico(h)
                bruto.unlink(missing_ok=True)
                log(f"Pronto: {titulo} ({c['broadcaster_name']}, {c['view_count']} views)"
                    + ("" if plano else " [sem Gemini]"))
            except Exception as ex:
                log(f"Falhou no clipe {c['id']}: {str(ex)[:200]}")
    finally:
        if gem:
            gem.__exit__(None, None, None)

    if "--sem-publicar" in args:
        log(f"Cortes prontos em {PRONTOS.resolve()}")
    else:
        publicar(h, cfg, enviados)
    shutil.rmtree(TRABALHO, ignore_errors=True)
    log("Fim.")


if __name__ == "__main__":
    main()
