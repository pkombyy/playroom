import yt_dlp
from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import asyncio
import json
import shutil
from typing import Any, Optional, Callable, Awaitable, List, Dict
from collections.abc import Sequence

CACHE_DIR = Path("tmp/music_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Семафор для ограничения параллельных загрузок (по умолчанию без ограничений)
_download_semaphore = asyncio.Semaphore(100)


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
            "outtmpl": outtmpl,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
        
        # Добавляем cookies только если файл существует
        cookies_path = Path("cookies.txt")
        if cookies_path.exists():
            ydl_opts["cookies"] = str(cookies_path)

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
        
        # Перемещаем файл в кэш
        shutil.move(str(mp3_path), str(cached_path))

        # 💾 сохраняем мета-файл
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"title": title}, f, ensure_ascii=False)

    # Читаем файл из кэша
    if not cached_path.exists():
        print(f"❌ Файл не найден в кэше: {cached_path}")
        return None
        
    with open(cached_path, "rb") as f:
        buf = BytesIO(f.read())
    buf.seek(0)

    return {"title": title, "buffer": buf, "hash": cache_key}


async def download_tracks_parallel(
    queries: Sequence[str],
    max_concurrent: int = 100,
    progress_callback: Optional[Callable[[str, str, int, int], Awaitable[None]]] = None
) -> Dict[str, dict | None]:
    """
    Параллельная загрузка нескольких треков.
    
    Args:
        queries: Список запросов для загрузки
        max_concurrent: Максимальное количество параллельных загрузок
        progress_callback: Callback для уведомлений о прогрессе
                          (query, status, completed, total)
                          status: "started", "completed", "failed", "cached"
    
    Returns:
        Словарь {query: result}, где result - результат download_track или None
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results: Dict[str, dict | None] = {}
    completed = 0
    total = len(queries)
    
    async def download_with_semaphore(query: str):
        nonlocal completed
        async with semaphore:
            if progress_callback:
                await progress_callback(query, "started", completed, total)
            
            # Проверяем кэш перед загрузкой
            cache_key = hashlib.md5(query.encode()).hexdigest()
            cached_path = CACHE_DIR / f"{cache_key}.mp3"
            if cached_path.exists():
                result = await download_track(query)
                results[query] = result
                completed += 1
                if progress_callback:
                    await progress_callback(query, "cached", completed, total)
                return result
            
            # Загружаем
            try:
                result = await download_track(query)
                results[query] = result
                completed += 1
                if progress_callback:
                    status = "completed" if result else "failed"
                    await progress_callback(query, status, completed, total)
                return result
            except Exception as e:
                print(f"💥 Ошибка при параллельной загрузке {query}: {e}")
                results[query] = None
                completed += 1
                if progress_callback:
                    await progress_callback(query, "failed", completed, total)
                return None
    
    # Запускаем все загрузки параллельно
    tasks = [download_with_semaphore(query) for query in queries]
    await asyncio.gather(*tasks, return_exceptions=True)
    
    return results


class DownloadQueue:
    """Очередь загрузок с управлением приоритетами и ограничением параллелизма."""
    
    def __init__(self, max_concurrent: int = 100):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.active_downloads: Dict[str, asyncio.Task] = {}
        self.results: Dict[str, dict | None] = {}
        self._worker_task: Optional[asyncio.Task] = None
    
    async def add(self, query: str, priority: int = 0) -> str:
        """
        Добавляет запрос в очередь.
        
        Args:
            query: Запрос для загрузки
            priority: Приоритет (больше = выше приоритет)
        
        Returns:
            ID задачи для отслеживания
        """
        task_id = hashlib.md5(query.encode()).hexdigest()[:8]
        await self.queue.put((priority, task_id, query))
        return task_id
    
    async def get_result(self, task_id: str, timeout: float = 300.0) -> dict | None:
        """
        Ожидает результат загрузки.
        
        Args:
            task_id: ID задачи
            timeout: Таймаут ожидания в секундах
        
        Returns:
            Результат загрузки или None
        """
        start_time = asyncio.get_event_loop().time()
        while True:
            if task_id in self.results:
                return self.results.pop(task_id)
            
            if asyncio.get_event_loop().time() - start_time > timeout:
                return None
            
            await asyncio.sleep(0.5)
    
    async def _worker(self):
        """Воркер для обработки очереди."""
        while True:
            try:
                priority, task_id, query = await self.queue.get()
                
                async with self.semaphore:
                    try:
                        result = await download_track(query)
                        self.results[task_id] = result
                    except Exception as e:
                        print(f"💥 Ошибка в очереди загрузок {query}: {e}")
                        self.results[task_id] = None
                
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"💥 Ошибка воркера очереди: {e}")
    
    def start(self):
        """Запускает воркер очереди."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
    
    async def stop(self):
        """Останавливает воркер очереди."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass


# Глобальная очередь загрузок
_global_queue: Optional[DownloadQueue] = None


def get_download_queue() -> DownloadQueue:
    """Получает глобальную очередь загрузок."""
    global _global_queue
    if _global_queue is None:
        _global_queue = DownloadQueue(max_concurrent=100)
        _global_queue.start()
    return _global_queue

