"""Usa o Gemini (gemini.google.com) pelo navegador, sem API: envia o clipe e pede um plano de edicao.

O Gemini web nao devolve video editado, entao ele faz a parte inteligente (achar o ponto de
interesse, legendar, titulo e descricao) e responde em JSON; o editar.py aplica com ffmpeg.

Uso:
  python gemini.py login            abre o navegador para voce entrar na conta Google (1 vez)
  python gemini.py testar video.mp4 envia um video e mostra o plano que o Gemini devolveu
Se algo quebrar (o Google muda a pagina), um print fica em gemini_erro.png.
"""
import base64
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

CAIXA = ("rich-textarea [contenteditable='true'], div.ql-editor[contenteditable='true'], "
         "[role='textbox'][contenteditable='true']")
ENVIAR = ("button[aria-label*='Send' i], button[aria-label*='Enviar' i], button.send-button")
PARAR = "button[aria-label*='Stop' i], button[aria-label*='Parar' i]"
RESPOSTA = "model-response, message-content, .model-response-text"
# a interface segue o idioma da conta (pt/en): todos os rotulos tem as duas versoes
BOTOES_ANEXO = ("button[aria-label*='Carregar' i], button[aria-label*='Upload' i], "
                "button[aria-label*='Add files' i], button[aria-label*='attach' i], "
                "button.upload-card-button")
ITEM_ARQUIVOS = re.compile(r"^\s*(Arquivos|Files|Upload files?|Enviar arquivos?|"
                           r"Fazer upload.*|Carregar arquivos?)\s*$", re.I)
AVISO_OK = re.compile(r"^\s*(Concordar|Agree|I agree|Accept|Aceitar)\s*$", re.I)
SELETOR_MODO = ("button[aria-label*='seletor de modo' i], button[aria-label*='mode picker' i], "
                "button[aria-label*='Open mode' i]")
AVATAR = "a[href*='SignOutOptions']"   # so existe com a conta logada, em qualquer idioma

JS_SOLTAR = """([nome, b64]) => {
    const bin = atob(b64), u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const dt = new DataTransfer();
    dt.items.add(new File([u8], nome, {type: 'video/mp4'}));
    const alvo = document.querySelector('rich-textarea') || document.body;
    for (const t of ['dragenter', 'dragover', 'drop'])
        alvo.dispatchEvent(new DragEvent(t, {bubbles: true, cancelable: true, dataTransfer: dt}));
}"""


def _sem_acento(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t.lower())
                   if unicodedata.category(c) != "Mn")


class GeminiErro(Exception):
    pass


class GeminiSemLogin(GeminiErro):
    pass


def prompt(clipe: dict, cfg: dict, duracao: float) -> str:
    e = cfg["edicao"]
    formato = ('{"ponto_interesse": {"inicio": "MM:SS.s", "fim": "MM:SS.s"}, '
               '"precisa_legenda": true, '
               '"legendas": [{"inicio": "MM:SS.s", "fim": "MM:SS.s", "texto": "..."}], '
               '"titulo": "...", "descricao": "...", "hashtags": ["#GTA6"]}')
    return (
        f"Voce e editor de videos curtos (Shorts/TikTok). Assista ao clipe anexado de GTA 6 "
        f"(streamer {clipe.get('broadcaster_name', '')}, titulo original \"{clipe.get('title', '')}\", "
        f"duracao {duracao:.0f} s, em portugues do Brasil). Responda SOMENTE com um JSON valido "
        f"dentro de um bloco de codigo, sem texto fora dele, neste formato: {formato} "
        f"Regras: ponto_interesse e o trecho mais engracado/impactante/surpreendente do clipe, "
        f"de no maximo {e.get('previa_max_seg', 4)} segundos, que sera mostrado no inicio como previa "
        f"(use tempos do clipe original). Se o clipe ja comeca no ponto alto, ponha o proprio inicio. "
        f"legendas: transcreva a fala em portugues do Brasil em frases curtas (ate 7 palavras cada, "
        f"com tempos do clipe original, sem sobreposicao); se quase nao ha fala ou ja existe legenda "
        f"na tela, use precisa_legenda false e legendas []. titulo: ate 70 caracteres, chamativo, "
        f"sem clickbait falso, sem hashtags. descricao: 1 a 2 frases. hashtags: 3 a 5."
    )


def _tempo(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    seg = 0.0
    for p in str(v).strip().replace(",", ".").split(":"):
        seg = seg * 60 + float(p)
    return seg


def extrair_json(texto: str) -> dict:
    i, j = texto.find("{"), texto.rfind("}")
    if i < 0 or j <= i:
        raise GeminiErro(f"resposta sem JSON: {texto[:200]!r}")
    return json.loads(texto[i:j + 1])


def validar(plano: dict, duracao: float, cfg: dict) -> dict:
    """Normaliza o plano: tempos em segundos, dentro do clipe, previa curta, legendas ordenadas."""
    e = cfg["edicao"]
    saida = {"previa": None, "legendas": [], "titulo": str(plano.get("titulo") or "").strip(),
             "descricao": str(plano.get("descricao") or "").strip(),
             "hashtags": [h.strip() if h.strip().startswith("#") else "#" + h.strip()
                          for h in (plano.get("hashtags") or []) if isinstance(h, str) and h.strip()]}
    try:
        pi = plano["ponto_interesse"]
        a = max(0.0, _tempo(pi["inicio"]))
        b = min(duracao, _tempo(pi["fim"]), a + e.get("previa_max_seg", 4))
        if b - a >= 1.0:
            saida["previa"] = (a, b)
    except (KeyError, TypeError, ValueError):
        pass
    if plano.get("precisa_legenda", True):
        legs = []
        for l in plano.get("legendas") or []:
            try:
                a, b = max(0.0, _tempo(l["inicio"])), min(duracao, _tempo(l["fim"]))
                txt = str(l["texto"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if txt and b - a >= 0.2:
                legs.append((a, b, txt))
        legs.sort()
        for k in range(len(legs) - 1):   # sem sobreposicao
            if legs[k][1] > legs[k + 1][0]:
                legs[k] = (legs[k][0], legs[k + 1][0], legs[k][2])
        saida["legendas"] = [l for l in legs if l[1] - l[0] >= 0.2]
    return saida


class Gemini:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.g = cfg["gemini"]
        self.pw = self.ctx = self.page = self.browser = self.proc = None

    # ------------------------------------------------------------ navegador
    # O Chrome e aberto "normal" (sem flags de automacao) com um perfil proprio; o Playwright so
    # se conecta a ele pela porta de depuracao. Assim o Google nao bloqueia o login.
    def _chrome(self) -> str:
        for c in (shutil.which("chrome"),
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                  str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe")):
            if c and Path(c).exists():
                return c
        raise GeminiErro("Chrome nao encontrado")

    def _lancar(self, extra: list[str]) -> subprocess.Popen:
        return subprocess.Popen([self._chrome(), f"--user-data-dir={Path(self.g['perfil']).resolve()}",
                                 "--no-first-run", "--no-default-browser-check", "--lang=en-US",
                                 *extra])

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        porta = int(self.g.get("porta_debug", 9333))
        self.proc = self._lancar([f"--remote-debugging-port={porta}", "--start-minimized",
                                  "about:blank"])
        self.pw = sync_playwright().start()
        erro = None
        for _ in range(30):
            try:
                self.browser = self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{porta}")
                break
            except Exception as e:
                erro = e
                time.sleep(1)
        else:
            self.__exit__()
            raise GeminiErro(f"nao consegui conectar ao Chrome (ele ja esta aberto com este "
                             f"perfil? feche-o): {str(erro)[:120]}")
        self.ctx = self.browser.contexts[0]
        self.page = self.ctx.new_page()
        return self

    def __exit__(self, *a):
        # fecha o Chrome de forma graciosa (Browser.close): matar o processo a forca perde os
        # cookies ainda nao gravados e desloga a conta do Google
        try:
            if self.browser:
                self.browser.new_browser_cdp_session().send("Browser.close")
        except Exception:
            pass
        if self.pw:
            try:
                self.pw.stop()
            except Exception:
                pass
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.wait(timeout=20)
            except Exception:
                self.proc.terminate()

    def _logado(self) -> bool:
        """O Gemini mostra a caixa de texto ate deslogado: o sinal real e o avatar da conta."""
        try:
            self.page.locator(CAIXA).first.wait_for(timeout=25000)
            self.page.locator(AVATAR).first.wait_for(state="attached", timeout=10000)
            return True
        except Exception:
            return False

    def _abrir(self):
        self.page.goto(self.g["url"], wait_until="domcontentloaded")
        if not self._logado():
            raise GeminiSemLogin("Gemini sem login (rode: python gemini.py login)")
        if self.g.get("modelo"):
            self._escolher_modelo(str(self.g["modelo"]))

    def _escolher_modelo(self, nome: str):
        """Seleciona o modo do Gemini pelo texto (ex.: 'Ajuda diaria', 'Auto'). Se nao achar, segue
        com o modo atual em vez de falhar."""
        p = self.page
        try:
            p.locator(SELETOR_MODO).first.click(timeout=5000)
            itens = p.locator("[role=menuitem], [role=menuitemradio], [role=option], "
                              ".mat-mdc-menu-item, button.bard-mode-list-button")
            itens.first.wait_for(timeout=4000)
            time.sleep(0.5)
            alvo = _sem_acento(nome)
            for i in range(itens.count()):
                if alvo in _sem_acento(itens.nth(i).inner_text()):
                    itens.nth(i).click(timeout=3000)
                    return
            print(f"  modelo '{nome}' nao encontrado no seletor; usando o atual", flush=True)
        except Exception:
            pass
        p.keyboard.press("Escape")

    def login(self):
        """Abre o Chrome normal no Gemini; espera voce entrar na conta e confirma sozinho."""
        with self:
            self.page.goto(self.g["url"], wait_until="domcontentloaded")
            self.proc_visivel()
            print("Entre na conta Google na janela do Chrome (clique em 'Sign in'). "
                  "Aguardando ate 10 min...", flush=True)
            fim = time.time() + 600
            while time.time() < fim:
                try:
                    if "gemini.google.com" in self.page.url and self._logado():
                        print("Login confirmado; sessao salva em", self.g["perfil"])
                        return
                except Exception:
                    pass
                time.sleep(3)
        raise GeminiErro("tempo esgotado sem concluir o login")

    def proc_visivel(self):
        try:
            self.page.bring_to_front()
            self.ctx.new_cdp_session(self.page).send(
                "Browser.setWindowBounds", {"windowId": self.ctx.new_cdp_session(self.page).send(
                    "Browser.getWindowForTarget")["windowId"], "bounds": {"windowState": "normal"}})
        except Exception:
            pass

    # ------------------------------------------------------------ interacao
    def _anexar(self, arquivo: Path):
        p = self.page
        anexou = False
        # 1) botao "+" -> menu -> item "Arquivos" -> seletor de arquivos nativo
        try:
            p.locator(BOTOES_ANEXO).first.click(timeout=5000)
            with p.expect_file_chooser(timeout=8000) as fc:
                p.get_by_text(ITEM_ARQUIVOS).first.click(timeout=4000)
            fc.value.set_files(str(arquivo))
            anexou = True
        except Exception:
            p.keyboard.press("Escape")
        # 2) senao, simula arrastar e soltar o arquivo sobre a pagina
        if not anexou:
            dados = base64.b64encode(arquivo.read_bytes()).decode()
            p.evaluate(JS_SOLTAR, [arquivo.name, dados])
        try:
            p.get_by_text(arquivo.name).first.wait_for(state="attached", timeout=40000)
        except Exception:
            raise GeminiErro("anexo do video nao apareceu na pagina")

    def _enviar(self, texto: str):
        p = self.page
        p.locator(CAIXA).first.click()
        p.keyboard.insert_text(texto)
        botao = p.locator(ENVIAR).first
        fim = time.time() + 180   # o botao so habilita quando o upload do video termina
        while time.time() < fim:
            try:
                if botao.is_enabled() and botao.get_attribute("aria-disabled") != "true":
                    botao.click()
                    self._aceitar_avisos()
                    return
            except Exception:
                pass
            time.sleep(1)
        raise GeminiErro("botao de enviar nao habilitou (upload do video travou?)")

    def _aceitar_avisos(self):
        """Aviso de direitos sobre videos (aparece ao enviar video): 'Concordar'."""
        try:
            self.page.get_by_role("button", name=AVISO_OK).first.click(timeout=4000)
        except Exception:
            pass

    def _esperar_resposta(self) -> str:
        p = self.page
        fim = time.time() + self.g.get("timeout_resposta_seg", 240)
        ultimo, estavel = "", 0
        while time.time() < fim:
            time.sleep(2)
            try:
                blocos = p.locator(RESPOSTA)
                texto = blocos.last.inner_text() if blocos.count() else ""
                gerando = p.locator(PARAR).count() > 0
            except Exception:
                continue
            if texto and texto == ultimo and not gerando:
                estavel += 1
                if estavel >= 2:
                    return texto
            else:
                estavel = 0
            ultimo = texto
        raise GeminiErro("tempo esgotado esperando a resposta do Gemini")

    # ------------------------------------------------------------ API
    def analisar(self, arquivo: Path, clipe: dict, duracao: float) -> dict:
        """Devolve o plano validado; tenta ate 2 vezes. Lanca GeminiErro se nao conseguir."""
        ultimo = None
        for _ in range(2):
            try:
                self._abrir()
                self._anexar(arquivo)
                self._enviar(prompt(clipe, self.cfg, duracao))
                texto = self._esperar_resposta()
                return validar(extrair_json(texto), duracao, self.cfg)
            except GeminiSemLogin:
                raise
            except (GeminiErro, json.JSONDecodeError) as e:
                ultimo = e
                try:
                    pass
                    self.page.screenshot(path="gemini_erro.png")
                except Exception:
                    pass
        raise GeminiErro(str(ultimo))


def _cfg() -> dict:
    return yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "login":
        Gemini(_cfg()).login()
    elif cmd == "testar" and len(sys.argv) > 2:
        from editar import duracao_video
        v = Path(sys.argv[2])
        with Gemini(_cfg()) as g:
            print(json.dumps(g.analisar(v, {"title": v.stem}, duracao_video(v)),
                             ensure_ascii=False, indent=2))
    else:
        print(__doc__)
