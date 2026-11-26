# cortes-gta

Uma vez por dia: busca na Twitch e na Kick os 5 clipes de GTA 6 em portugues mais vistos de cada uma
(ultimas 24 h, sem repetir os ja usados), pede ao Gemini (pelo navegador, sem API) o ponto de interesse, a
legenda e o titulo, edita com ffmpeg e envia ao YouTube e ao TikTok.

Pipeline: Twitch API / Kick -> yt-dlp (download) -> Gemini web (plano de edicao em JSON) -> ffmpeg
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
   Para postar direto no perfil (privado enquanto o app nao for auditado; funciona no Sandbox):
   `publicacao.tiktok_direto: true` no `config.yaml` e `python enviar_tiktok.py login --direto`.
   Kick: nao precisa de login nem credenciais (usa a API publica do site). Desligue com `kick.ativo: false`.
6. Ajustes em `config.yaml` (jogo, quantidade, previa, legenda, formato, privacidade).

## Usar
- `rodar.bat` / `python rodar.py`: rotina completa. `--sem-publicar`: so edita (veja `prontos/`).
  `--sem-gemini`: edita sem o Gemini. `--so-publicar`: nao busca nem edita, so envia ao YouTube/TikTok
  o que ja esta pronto e pendente (use depois de limite de cota/rascunhos).
- `python repostar_tiktok.py pasta <pasta>`: reposta pela API do TikTok videos ja publicados (ex.: os
  postados a mao). Enfileira os originais da pasta (legenda opcional em `<nome>.txt`) so para o TikTok;
  o envio segue o limite diario normal. Sem os originais: `listar @usuario` (gera `repostar.csv` para
  marcar) e `baixar`. A API nao apaga videos: apague o antigo no app antes de publicar o rascunho.
- `agendar.bat [HH:MM]`: agenda todo dia (padrao 09:00). Computador ligado e usuario logado.
- `historico.json` evita duplicados e guarda o que ja foi enviado; envios que falharam (cota, rede)
  sao retomados na proxima execucao. `log.txt` tem o registro. Se o Gemini quebrar, veja `gemini_erro.png`.

## Observacoes
- Desfoque no TikTok: o Gemini aponta os trechos com conteudo obsceno (nudez/sexo) e o TikTok recebe
  `prontos/<id>_tiktok.mp4` com eles desfocados (inclusive na previa); o YouTube usa o video sem desfoque.
  So gera a versao extra quando ha trechos. Desligue com `edicao.desfoque_tiktok: false`. Sem o Gemini
  (`--sem-gemini` ou falha) nao ha deteccao, entao nada e desfocado.
- A Twitch nao tem curtidas em clipes: o ranking e por visualizacoes (na Kick tambem).
- Kick: o clipe nao informa o idioma, entao usa-se o idioma do canal (da live atual ou do ultimo VOD),
  guardado em `kick_canais.json`. Canais sem live/VOD recente ficam de fora; use `kick.canais_ignorar`
  para vetar algum. A API da Kick nao e oficial/documentada e pode mudar.
- Com Twitch + Kick sao ate 10 cortes novos por dia, mas YouTube/TikTok aceitam ~5 por dia
  (`max_*_por_dia`): os mais vistos vao primeiro e o resto espera a proxima execucao.
- Videos enviados por app nao auditado ficam privados no YouTube (`privacidade_youtube`).
- Clipes sao de terceiros: credite (a descricao ja leva o link do clipe) e confirme que o uso/monetizacao
  e permitido pelos streamers e pelas regras da Twitch.
