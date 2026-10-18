# Deploy no Railway

1. Suba **os arquivos soltos** (não o .zip) na raiz do repositório do GitHub:
   `bot.py`, `requirements.txt`, `Dockerfile`, `.dockerignore`, `.gitignore`, `.env.example`, `README.md` e a pasta `music`.
2. No Railway: **New Project → Deploy from GitHub repo** e escolha o repositório.
3. Aba **Variables**, crie:
   - `DISCORD_TOKEN` = token do bot (obrigatório)
   - `GUILD_ID` = ID do servidor
   - `VOICE_CHANNEL_ID` = ID do canal de voz (só se usar AUTO_JOIN)
   - `AUTO_JOIN` = `false` (use `true` só se quiser que entre sozinho e toque a pasta music)
   - `AUTO_LOOP` = `false`
   - `SPOTIFY_CLIENT_ID` e `SPOTIFY_CLIENT_SECRET` (opcionais)
4. Aguarde o deploy ficar **Active** e abra **View Logs**: deve aparecer `Conectado como ...`.
5. No Discord, entre num canal de voz e use `/play`.

O `Dockerfile` instala FFmpeg, libopus e o Deno (necessário para o yt-dlp acessar o YouTube) e inicia o bot com `python bot.py`. O Railway usa o Dockerfile automaticamente; se não usar, vá em Settings > Build e escolha Dockerfile como builder.
