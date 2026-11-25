"""Reposta pela API videos que ja estao no perfil do TikTok (ex.: os publicados a mao).

Com os arquivos originais (recomendado, sem perda de qualidade):
  python repostar_tiktok.py pasta C:\\caminho\\da\\pasta
  Enfileira todos os videos da pasta (deixe nela so os que quer repostar). Legenda opcional:
  um .txt com o mesmo nome do video (ex.: corte1.mp4 + corte1.txt). Depois siga o passo 3.

Sem os originais (baixa do proprio TikTok):

Passo 1 - listar o perfil (nao precisa de login, usa o yt-dlp):
  python repostar_tiktok.py listar @seu_usuario
  Gera repostar.csv com todos os videos do perfil (views, data, legenda). Abra no Excel/Bloco de
  Notas e deixe "s" na coluna repostar SO nos videos que voce quer repostar (os demais: "n").

Passo 2 - baixar e enfileirar:
  python repostar_tiktok.py baixar
  Baixa os marcados para prontos/repost/ e os coloca no historico.json como pendentes so para o
  TikTok (nao vao ao YouTube). A rotina diaria (ou: python rodar.py --so-publicar) envia ate
  max_tiktok_por_dia rascunhos por execucao, os mais vistos primeiro.

Passo 3 - no app: para cada rascunho que chegar, APAGUE o video antigo e so depois publique o
rascunho (a API do TikTok nao apaga videos). A legenda original de cada um fica em
prontos/repost/<id>.txt para copiar e colar.
"""
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from rodar import PRONTOS, carregar_historico, log, salvar_historico

LISTA = Path("repostar.csv")
PASTA = PRONTOS / "repost"
CAMPOS = ["repostar", "id", "views", "data", "legenda", "url"]


def listar(usuario: str) -> None:
    usuario = usuario.lstrip("@")
    perfil = f"https://www.tiktok.com/@{usuario}"
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "--dump-json", "--skip-download",
                        "--ignore-errors", perfil], capture_output=True, text=True, encoding="utf-8")
    videos = [json.loads(l) for l in r.stdout.splitlines() if l.strip().startswith("{")]
    if not videos:
        raise SystemExit(f"Nenhum video encontrado em {perfil}\n{r.stderr[-800:]}")
    with LISTA.open("w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: o Excel le acentos
        w = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=";")
        w.writeheader()
        for v in videos:
            ts = v.get("timestamp")
            w.writerow({"repostar": "n", "id": v["id"], "views": v.get("view_count") or 0,
                        "data": datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M") if ts else "",
                        "legenda": (v.get("description") or v.get("title") or "").replace("\n", " "),
                        "url": v.get("webpage_url") or f"{perfil}/video/{v['id']}"})
    print(f"{len(videos)} video(s) em {LISTA}. Troque 'n' por 's' nos que quer repostar e rode: "
          f"python repostar_tiktok.py baixar")


def baixar() -> None:
    if not LISTA.exists():
        raise SystemExit("Rode antes: python repostar_tiktok.py listar @seu_usuario")
    with LISTA.open(encoding="utf-8-sig") as f:
        marcados = [l for l in csv.DictReader(f, delimiter=";")
                    if l["repostar"].strip().lower() in ("s", "sim", "x", "1")]
    if not marcados:
        raise SystemExit(f"Nenhum video marcado com 's' em {LISTA}")
    PASTA.mkdir(parents=True, exist_ok=True)
    h = carregar_historico()
    novos = 0
    for l in marcados:
        chave = f"repost-{l['id']}"
        if chave in h:
            print(f"Ja enfileirado: {l['legenda'][:60]}")
            continue
        destino = PASTA / f"{l['id']}.mp4"
        if not destino.exists():
            r = subprocess.run([sys.executable, "-m", "yt_dlp", "-f", "best[ext=mp4]/best",
                                "--merge-output-format", "mp4", "-o", str(destino), l["url"]],
                               capture_output=True, text=True, encoding="utf-8")
            if r.returncode != 0 or not destino.exists():
                log(f"Repost: falhou ao baixar {l['url']}: {r.stderr.strip()[-200:]}")
                continue
        (PASTA / f"{l['id']}.txt").write_text(l["legenda"], encoding="utf-8")
        h[chave] = {"id": chave, "arquivo": str(destino), "arquivo_tiktok": None,
                    "titulo": l["legenda"][:150], "descricao": l["legenda"], "hashtags": [],
                    "views": int(l["views"] or 0), "url": l["url"], "fonte": "repost",
                    "so_tiktok": True, "data": datetime.now().isoformat(timespec="seconds")}
        salvar_historico(h)
        novos += 1
        log(f"Repost enfileirado: {l['legenda'][:60]}")
    print(f"{novos} video(s) enfileirado(s). Envie com: python rodar.py --so-publicar "
          f"(ou espere a rotina diaria).")


def pasta(origem: str) -> None:
    """Enfileira os arquivos originais de uma pasta (melhor que baixar: sem recompressao)."""
    videos = sorted(p for p in Path(origem).iterdir()
                    if p.suffix.lower() in (".mp4", ".mov", ".webm") and p.is_file())
    if not videos:
        raise SystemExit(f"Nenhum video (.mp4/.mov/.webm) em {origem}")
    h = carregar_historico()
    novos = 0
    for i, v in enumerate(videos):
        chave = f"repost-{v.stem}"
        if chave in h:
            print(f"Ja enfileirado: {v.name}")
            continue
        txt = v.with_suffix(".txt")   # legenda opcional ao lado do video, com o mesmo nome
        legenda = txt.read_text(encoding="utf-8").strip() if txt.exists() else v.stem
        h[chave] = {"id": chave, "arquivo": str(v.resolve()), "arquivo_tiktok": None,
                    "titulo": legenda[:150], "descricao": legenda, "hashtags": [],
                    "views": len(videos) - i,   # mantem a ordem alfabetica dos arquivos no envio
                    "url": "", "fonte": "repost", "so_tiktok": True,
                    "data": datetime.now().isoformat(timespec="seconds")}
        novos += 1
        log(f"Repost enfileirado: {v.name}")
    salvar_historico(h)
    print(f"{novos} video(s) enfileirado(s). Envie com: python rodar.py --so-publicar "
          f"(ou espere a rotina diaria). Nao mova nem apague os arquivos ate serem enviados.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.argv[1:2] == ["listar"] and len(sys.argv) == 3:
        listar(sys.argv[2])
    elif sys.argv[1:] == ["baixar"]:
        baixar()
    elif sys.argv[1:2] == ["pasta"] and len(sys.argv) == 3:
        pasta(sys.argv[2])
    else:
        print(__doc__)
