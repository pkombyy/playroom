import yt_dlp
from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import asyncio
import json
from typing import Any, Optional

CACHE_DIR = Path("tmp/music_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


async def download_track(query: str) -> dict | None:
    """
    Возвращает словарь с ключами:
    {
        "title": str,     # Название трека
        "buffer": BytesIO,
        "hash": str       # Хеш-файл
    }
    """
    cache_key = hashlib.md5(query.encode()).hexdigest()
    cached_path = CACHE_DIR / f"{cache_key}.mp3"
    meta_path = CACHE_DIR / f"{cache_key}.json"

    # ⚡ Если есть в кэше — возвращаем из него
    if cached_path.exists():
        title = query  # по дефолту возвращаем то, что ввёл пользователь
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    title = meta.get("title", title)
            except Exception:
                pass
        with open(cached_path, "rb") as f:
            buf = BytesIO(f.read())
        buf.seek(0)
        return {"title": title, "buffer": buf, "hash": cache_key}

    # ⏳ если нет — качаем
    with tempfile.TemporaryDirectory() as tmpdir:
        outtmpl = str(Path(tmpdir) / "%(title)s.%(ext)s")

        ydl_opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "default_search": "ytsearch1",
            "quiet": True,
            "cookies": "cookies.txt",
            "outtmpl": outtmpl,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }

        def run_ydl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore
                info = ydl.extract_info(query, download=True)
                if "entries" in info:
                    info = info["entries"][0]
                return info

        try:
            info = await asyncio.to_thread(run_ydl)
        except Exception as e:
            print(f"💥 Ошибка при загрузке {query}: {e}")
            return None

        mp3_files = list(Path(tmpdir).glob("*.mp3"))
        if not mp3_files:
            print(f"❌ yt_dlp не создал mp3 для {query}")
            return None

        title = info.get("title", query)
        mp3_path = mp3_files[0]
        mp3_path.replace(cached_path)

        # 💾 сохраняем мета-файл
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"title": title}, f, ensure_ascii=False)

    with open(cached_path, "rb") as f:
        buf = BytesIO(f.read())
    buf.seek(0)

    return {"title": title, "buffer": buf, "hash": cache_key}

