import asyncio
import os
import random
from pathlib import Path
from urllib.parse import urlparse
import re
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", "0") or 0)
AUTO_JOIN = os.getenv("AUTO_JOIN", "false").lower() in {"1", "true", "yes", "on"}
AUTO_LOOP = os.getenv("AUTO_LOOP", "true").lower() in {"1", "true", "yes", "on"}
SHUFFLE_ON_START = os.getenv("SHUFFLE_ON_START", "false").lower() in {"1", "true", "yes", "on"}
MUSIC_DIR = Path(os.getenv("MUSIC_DIR", "music")).resolve()
MUSIC_DIR.mkdir(parents=True, exist_ok=True)
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN está vazio. Preencha o arquivo .env.")

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"}
FFMPEG_OPTIONS = {"options": "-vn"}
FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

queues: dict[int, list[str]] = {}
loop_enabled: dict[int, bool] = {}
now_playing: dict[int, str] = {}
auto_started: set[int] = set()
sync_done = False


def guild_queue(guild_id: int) -> list[str]:
    return queues.setdefault(guild_id, [])


def local_audio_path(name: str) -> Path | None:
    # Only allow files inside ./music; reject traversal and arbitrary local paths.
    candidate = (MUSIC_DIR / name).resolve()
    if MUSIC_DIR not in candidate.parents or not candidate.is_file():
        return None
    if candidate.suffix.lower() not in AUDIO_EXTENSIONS:
        return None
    return candidate


def is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def resolve_local_or_direct(value: str) -> tuple[str, str, bool]:
    path = local_audio_path(value)
    if path:
        return str(path), path.name, False
    if is_http_url(value):
        return value, value, True
    raise ValueError("Fonte não reconhecida. Use nome de música, link do YouTube, link de playlist ou arquivo local.")


def ytdlp_info(query: str, playlist: bool = False):
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist" if playlist else False,
            "skip_download": True, "noplaylist": not playlist, "default_search": "ytsearch1",
            "format": "bestaudio/best"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(query, download=False)


def resolve_track_sync(item: str):
    """Return playable stream URL and a friendly title. Supports local files, direct URLs and YouTube search/URLs."""
    path = local_audio_path(item)
    if path:
        return str(path), path.name, False
    if item.startswith("search:"):
        query = item[7:].strip()
        info = ytdlp_info("ytsearch1:" + query)
    elif "youtube.com/" in item or "youtu.be/" in item:
        info = ytdlp_info(item)
    elif is_http_url(item):
        return item, item, True
    else:
        info = ytdlp_info("ytsearch1:" + item)
    if info.get("entries"):
        info = next((e for e in info["entries"] if e), None)
    if not info or not info.get("url"):
        raise ValueError("Não encontrei uma faixa reproduzível para essa pesquisa.")
    return info["url"], info.get("title", item), True


def spotify_tracks_sync(url: str) -> list[str]:
    if not (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET):
        raise ValueError("Para links do Spotify, configure SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET no .env. O YouTube funciona sem isso.")
    client = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET))
    match = re.search(r"open\.spotify\.com/(?:intl-[^/]+/)?(playlist|album|track)/([A-Za-z0-9]+)", url)
    if not match:
        raise ValueError("Link do Spotify inválido. Usa link público de playlist, álbum ou faixa.")
    kind, item_id = match.groups()
    queries = []
    if kind == "track":
        track = client.track(item_id)
        queries.append(track["name"] + " " + " ".join(a["name"] for a in track["artists"]))
    elif kind == "playlist":
        results = client.playlist_items(item_id, limit=100, additional_types=("track",))
        while True:
            for row in results.get("items", []):
                t = row.get("track")
                if t and t.get("name"):
                    queries.append(t["name"] + " " + " ".join(a["name"] for a in t["artists"]))
            if not results.get("next") or len(queries) >= 100:
                break
            results = client.next(results)
    else:
        results = client.album_tracks(item_id, limit=50)
        for t in results.get("items", []):
            queries.append(t["name"] + " " + " ".join(a["name"] for a in t["artists"]))
    return queries


async def get_voice(interaction: discord.Interaction, auto_channel: bool = False):
    if not interaction.guild:
        raise app_commands.AppCommandError("Este comando só funciona dentro de um servidor.")
    voice = interaction.guild.voice_client
    if voice and voice.is_connected():
        return voice
    channel = None
    if auto_channel and VOICE_CHANNEL_ID:
        candidate = interaction.guild.get_channel(VOICE_CHANNEL_ID)
        if isinstance(candidate, (discord.VoiceChannel, discord.StageChannel)):
            channel = candidate
    if channel is None:
        user_voice = getattr(interaction.user, "voice", None)
        channel = user_voice.channel if user_voice else None
    if channel is None:
        raise app_commands.AppCommandError(
            "Entre num canal de voz primeiro ou configure VOICE_CHANNEL_ID no .env."
        )
    return await channel.connect()


async def play_next(guild: discord.Guild):
    voice = guild.voice_client
    if not voice or not voice.is_connected() or voice.is_playing() or voice.is_paused():
        return

    q = guild_queue(guild.id)
    if not q:
        if loop_enabled.get(guild.id, AUTO_LOOP):
            files = [p.name for p in MUSIC_DIR.iterdir()
                     if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]
            if SHUFFLE_ON_START:
                random.shuffle(files)
            q.extend(files)
        if not q:
            now_playing.pop(guild.id, None)
            return

    item = q.pop(0)
    try:
        source, title, network = await asyncio.to_thread(resolve_track_sync, item)
        audio = discord.FFmpegPCMAudio(
            source,
            before_options=FFMPEG_BEFORE_OPTIONS if network else None,
            **FFMPEG_OPTIONS,
        )
        now_playing[guild.id] = title

        def after(error):
            if error:
                print(f"[audio] erro ao tocar {title}: {error}")
            future = asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)
            try:
                future.result(timeout=30)
            except Exception as exc:
                print(f"[fila] erro ao avançar: {exc}")

        voice.play(audio, after=after)
        print(f"[tocando] {title}")
    except Exception as exc:
        print(f"[audio] não foi possível tocar {item!r}: {exc}")
        # Try the next item without getting stuck on a broken source.
        await play_next(guild)


@bot.event
async def on_ready():
    global sync_done
    print(f"Conectado como {bot.user} (ID {bot.user.id})")
    if not sync_done:
        try:
            if GUILD_ID:
                guild_obj = discord.Object(id=GUILD_ID)
                bot.tree.copy_global_to(guild=guild_obj)
                await bot.tree.sync(guild=guild_obj)
                print("Comandos sincronizados no servidor configurado.")
            else:
                await bot.tree.sync()
                print("Comandos globais sincronizados; podem demorar para aparecer.")
            sync_done = True
        except Exception as exc:
            print(f"Falha ao sincronizar comandos: {exc}")

    if AUTO_JOIN and VOICE_CHANNEL_ID:
        for guild in bot.guilds:
            if GUILD_ID and guild.id != GUILD_ID:
                continue
            if guild.id in auto_started:
                continue
            channel = guild.get_channel(VOICE_CHANNEL_ID)
            if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                print(f"Canal {VOICE_CHANNEL_ID} não encontrado no servidor {guild.id}.")
                continue
            try:
                if not guild.voice_client:
                    await channel.connect()
                auto_started.add(guild.id)
                loop_enabled[guild.id] = AUTO_LOOP
                await play_next(guild)
            except Exception as exc:
                print(f"Falha na entrada automática: {exc}")


@bot.tree.command(name="join", description="Entra no teu canal de voz")
async def join(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        await get_voice(interaction)
        await interaction.followup.send("Conectado ao canal de voz. 🎧", ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(str(exc), ephemeral=True)


@bot.tree.command(name="play", description="Toca pelo nome da música ou link do YouTube/áudio")
@app_commands.describe(faixa="Nome da música, link do YouTube ou arquivo local")
async def play(interaction: discord.Interaction, faixa: str):
    await interaction.response.defer(thinking=True)
    try:
        await get_voice(interaction)
        item = faixa.strip()
        guild_queue(interaction.guild_id).append(item if local_audio_path(item) or is_http_url(item) else "search:" + item)
        await interaction.followup.send(f"Adicionado à fila: **{faixa}**. Vou procurar uma versão reproduzível. 🔎")
        await play_next(interaction.guild)
    except Exception as exc:
        await interaction.followup.send(f"Não consegui adicionar essa faixa: {exc}")


@bot.tree.command(name="playlist", description="Toca playlist do YouTube/Spotify ou arquivos locais")
@app_commands.describe(link="Link público de playlist/álbum do YouTube ou Spotify (ou deixa vazio para pasta music)")
async def playlist(interaction: discord.Interaction, link: str = ""):
    if not interaction.guild:
        await interaction.response.send_message("Use dentro de um servidor.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    try:
        await get_voice(interaction)
        link = link.strip()
        if not link:
            files = sorted(p.name for p in MUSIC_DIR.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS)
            if not files:
                await interaction.followup.send("A pasta `music` está vazia. Envia um link de playlist ou coloca arquivos de áudio nela.", ephemeral=True)
                return
            guild_queue(interaction.guild_id).extend(files)
            count = len(files)
        elif "open.spotify.com/" in link:
            tracks = await asyncio.to_thread(spotify_tracks_sync, link)
            guild_queue(interaction.guild_id).extend("search:" + t for t in tracks)
            count = len(tracks)
        elif "youtube.com/playlist" in link or "youtube.com/watch" in link and "list=" in link:
            info = await asyncio.to_thread(ytdlp_info, link, True)
            entries = info.get("entries") or []
            videos = ["https://www.youtube.com/watch?v=" + e["id"] for e in entries if e and e.get("id")]
            if not videos:
                raise ValueError("Não consegui ler as faixas dessa playlist do YouTube.")
            guild_queue(interaction.guild_id).extend(videos)
            count = len(videos)
        elif "youtube.com/" in link or "youtu.be/" in link:
            guild_queue(interaction.guild_id).append(link)
            count = 1
        else:
            raise ValueError("Manda um link público de playlist/álbum do YouTube ou Spotify.")
        await interaction.followup.send(f"Adicionei **{count}** faixa(s) à fila. 🎶")
        await play_next(interaction.guild)
    except Exception as exc:
        await interaction.followup.send(f"Não consegui carregar a playlist: {exc}", ephemeral=True)


@bot.tree.command(name="queue", description="Mostra a faixa atual e a fila")
async def queue_cmd(interaction: discord.Interaction):
    q = guild_queue(interaction.guild_id)
    current = now_playing.get(interaction.guild_id, "Nada tocando")
    upcoming = "\n".join(f"{i}. {item}" for i, item in enumerate(q[:15], 1)) or "Fila vazia."
    await interaction.response.send_message(
        f"**Agora:** {current}\n**Próximas faixas:**\n{upcoming}", ephemeral=True
    )


@bot.tree.command(name="skip", description="Pula para a próxima faixa")
async def skip(interaction: discord.Interaction):
    voice = interaction.guild.voice_client if interaction.guild else None
    if voice and (voice.is_playing() or voice.is_paused()):
        voice.stop()
        await interaction.response.send_message("Pulando para a próxima faixa. ⏭️")
    else:
        await interaction.response.send_message("Não há faixa tocando.", ephemeral=True)


@bot.tree.command(name="pause", description="Pausa a música")
async def pause(interaction: discord.Interaction):
    voice = interaction.guild.voice_client if interaction.guild else None
    if voice and voice.is_playing():
        voice.pause()
        await interaction.response.send_message("Música pausada. ⏸️")
    else:
        await interaction.response.send_message("Não há música tocando.", ephemeral=True)


@bot.tree.command(name="resume", description="Retoma a música")
async def resume(interaction: discord.Interaction):
    voice = interaction.guild.voice_client if interaction.guild else None
    if voice and voice.is_paused():
        voice.resume()
        await interaction.response.send_message("Música retomada. ▶️")
    else:
        await interaction.response.send_message("Não há música pausada.", ephemeral=True)


@bot.tree.command(name="loop", description="Liga ou desliga a repetição da pasta music")
@app_commands.describe(ativado="Quando ligado, a pasta music volta à fila ao terminar")
async def loop_cmd(interaction: discord.Interaction, ativado: bool):
    loop_enabled[interaction.guild_id] = ativado
    await interaction.response.send_message(f"Loop: **{'ligado' if ativado else 'desligado'}** 🔁")


@bot.tree.command(name="shuffle", description="Embaralha as faixas que ainda estão na fila")
async def shuffle_cmd(interaction: discord.Interaction):
    q = guild_queue(interaction.guild_id)
    random.shuffle(q)
    await interaction.response.send_message(f"Fila embaralhada ({len(q)} faixa(s)). 🔀")


@bot.tree.command(name="leave", description="Sai do canal de voz e limpa a fila")
async def leave(interaction: discord.Interaction):
    voice = interaction.guild.voice_client if interaction.guild else None
    if voice:
        await voice.disconnect()
        queues[interaction.guild_id] = []
        now_playing.pop(interaction.guild_id, None)
        await interaction.response.send_message("Desconectado e fila limpa. 👋")
    else:
        await interaction.response.send_message("Não estou num canal de voz.", ephemeral=True)


@bot.tree.error
async def command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    message = str(getattr(error, "original", error))
    if interaction.response.is_done():
        await interaction.followup.send(f"Erro: {message}", ephemeral=True)
    else:
        await interaction.response.send_message(f"Erro: {message}", ephemeral=True)


async def main():
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
