# Discord DJ Pro — pesquisa por nome e playlists

Bot de música para servidor Discord usando `discord.py`, FFmpeg e `yt-dlp`.

## O que tem
- `/play faixa:<nome>` procura uma faixa no YouTube e tenta tocar uma versão disponível.
- `/play faixa:<link do YouTube>` toca um vídeo individual.
- `/playlist link:<link>` adiciona uma playlist do YouTube; também aceita playlist/álbum/faixa pública do Spotify se configurar a API do Spotify.
- `/playlist` sem link toca arquivos locais da pasta `music`.
- `/queue`, `/skip`, `/pause`, `/resume`, `/loop`, `/shuffle`, `/join` e `/leave`.
- Entrada automática opcional no canal configurado.

## Instalação no Windows
1. Instale Python 3.10 ou mais recente e FFmpeg. Confirme que `ffmpeg -version` funciona no CMD. Se não funcionar, adicione a pasta `bin` do FFmpeg ao PATH e abra um CMD novo.
2. Extraia o ZIP e abra CMD dentro da pasta do projeto.
3. Crie/ative seu ambiente virtual, se ainda não existir:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   ```
4. Instale dependências:
   ```bat
   python -m pip install -U pip
   python -m pip install -r requirements.txt
   ```
5. Copie `.env.example` para `.env` e edite `.env` com seu token e IDs. Nunca compartilhe o token.
6. Execute `python bot.py`.

## Configuração do .env
- `DISCORD_TOKEN`: token do bot do Discord.
- `GUILD_ID`: ID do servidor.
- `VOICE_CHANNEL_ID`: ID do canal de voz para auto-entrar.
- `AUTO_JOIN=true`: tenta entrar no canal configurado quando inicia.
- `AUTO_LOOP=true`: repete os arquivos locais da pasta music quando a fila acabar; não repete automaticamente playlists online.
- `SPOTIFY_CLIENT_ID` e `SPOTIFY_CLIENT_SECRET`: opcionais, necessários para ler metadados de links Spotify. Crie um app em https://developer.spotify.com/dashboard/ e use Client ID/Secret. Nunca use sua senha do Spotify.

## Uso
No chat do Discord digite `/` e selecione o comando:
- `/play faixa: Daft Punk - One More Time`
- `/playlist link: https://www.youtube.com/playlist?list=...`
- `/playlist link: https://open.spotify.com/playlist/...`
- `/playlist` para tocar arquivos da pasta `music`.

Para Spotify, o bot lê os nomes das faixas via API e procura versões correspondentes no YouTube; não transmite áudio diretamente do Spotify e a correspondência pode não ser perfeita. Reproduza somente conteúdo que você tenha direito/autorização para usar e respeite os termos das plataformas. Links privados ou indisponíveis podem falhar.

## Importante
- O computador/servidor precisa ficar ligado e o processo rodando para o bot ficar 24/7.
- O bot precisa das permissões de ver/conectar/falar no canal. Convide-o com os scopes `bot` e `applications.commands`.
- Comandos sincronizam no servidor configurado por `GUILD_ID`; reinicie o bot se mudar código ou dependências.
