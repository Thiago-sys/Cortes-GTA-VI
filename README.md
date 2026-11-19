# cortes-gta

Uma vez por dia: busca na Twitch os 5 clipes de GTA 6 em portugues mais vistos das ultimas 24 h
(sem repetir os ja usados), pede ao Gemini (pelo navegador, sem API) o ponto de interesse, a
legenda e o titulo, edita com ffmpeg e envia ao YouTube e ao TikTok.

Pipeline: Twitch API -> yt-dlp (download) -> Gemini web (plano de edicao em JSON) -> ffmpeg
(previa do ponto de interesse no inicio + legenda + formato vertical 9:16) -> YouTube / TikTok.
O Gemini web nao devolve video, entao ele decide e o ffmpeg executa. Se o Gemini falhar, o
clipe sai sem previa/legenda (titulo do proprio clipe) em vez de ser perdido.

## Configurar (uma vez)
1. Python 3.10+, ffmpeg e Google Chrome instalados. `pip install -r requirements.txt`
2. Twitch: crie um app em https://dev.twitch.tv/console/apps e preencha `twitch_client.json`.
3. Gemini: `python gemini.py login` (entre na conta Google na janela; a sessao fica em `.perfil_gemini`).
   Teste: `python gemini.py testar algum_clipe.mp4`.
4. YouTube: `client_secret.json` (OAuth Desktop, YouTube Data API v3) e `python enviar_youtube.py login`.
5. TikTok: `tiktok_client.json` e `python enviar_tiktok.py login` (rascunhos: voce toca em publicar no app).
6. Ajustes em `config.yaml` (jogo, quantidade, previa, legenda, formato, privacidade).

## Usar
- `rodar.bat` / `python rodar.py`: rotina completa. `--sem-publicar`: so edita (veja `prontos/`).
  `--sem-gemini`: edita sem o Gemini.
- `agendar.bat [HH:MM]`: agenda todo dia (padrao 09:00). Computador ligado e usuario logado.
- `historico.json` evita duplicados e guarda o que ja foi enviado; envios que falharam (cota, rede)
  sao retomados na proxima execucao. `log.txt` tem o registro. Se o Gemini quebrar, veja `gemini_erro.png`.

## Observacoes
- A Twitch nao tem curtidas em clipes: o ranking e por visualizacoes.
- Videos enviados por app nao auditado ficam privados no YouTube (`privacidade_youtube`).
- Clipes sao de terceiros: credite (a descricao ja leva o link do clipe) e confirme que o uso/monetizacao
  e permitido pelos streamers e pelas regras da Twitch.
