#!/usr/bin/env python3
"""
Тестовый скрипт для проверки загрузки треков с YouTube
"""
import asyncio
import sys
from pathlib import Path
from utils.youtube import download_track


async def test_download(query: str):
    """Тестирует загрузку трека по запросу"""
    print(f"\n🔍 Тестирую загрузку: '{query}'")
    print("=" * 60)
    
    try:
        result = await download_track(query)
        
        if result is None:
            print("❌ Ошибка: download_track вернул None")
            return False
        
        print(f"✅ Загрузка успешна!")
        print(f"📝 Название: {result['title']}")
        print(f"🔑 Хеш: {result['hash']}")
        
        buffer = result['buffer']
        size = len(buffer.getvalue())
        print(f"📦 Размер файла: {size:,} байт ({size / 1024 / 1024:.2f} MB)")
        
        # Проверяем, что это действительно MP3
        buffer.seek(0)
        header = buffer.read(3)
        if header == b'ID3' or header == b'\xff\xfb' or header == b'\xff\xf3':
            print("✅ Файл похож на MP3 (проверка заголовка)")
        else:
            print(f"⚠️  Необычный заголовок: {header}")
        
        # Проверяем кэш
        cache_path = Path("tmp/music_cache") / f"{result['hash']}.mp3"
        if cache_path.exists():
            cache_size = cache_path.stat().st_size
            print(f"💾 Файл сохранён в кэш: {cache_path} ({cache_size:,} байт)")
        else:
            print(f"⚠️  Файл не найден в кэше: {cache_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при загрузке: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Основная функция тестирования"""
    print("🎵 Тестирование загрузки треков с YouTube")
    print("=" * 60)
    
    # Проверяем наличие yt-dlp
    try:
        import yt_dlp
        print(f"✅ yt-dlp установлен: версия {yt_dlp.version.__version__}")
    except ImportError:
        print("❌ yt-dlp не установлен!")
        return
    
    # Проверяем наличие FFmpeg (опционально, но желательно)
    import shutil
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        print(f"✅ FFmpeg найден: {ffmpeg_path}")
    else:
        print("⚠️  FFmpeg не найден в PATH. Конвертация в MP3 может не работать.")
        print("   Установите FFmpeg: https://ffmpeg.org/download.html")
    
    # Проверяем cookies.txt (опционально)
    cookies_path = Path("cookies.txt")
    if cookies_path.exists():
        print(f"✅ cookies.txt найден")
    else:
        print("ℹ️  cookies.txt не найден (опционально, но может помочь обойти ограничения)")
    
    # Тестовые запросы
    test_queries = [
        "Never Gonna Give You Up",  # Популярный трек для теста
    ]
    
    # Если передан аргумент командной строки, используем его
    if len(sys.argv) > 1:
        test_queries = [sys.argv[1]]
    
    results = []
    for query in test_queries:
        success = await test_download(query)
        results.append((query, success))
        await asyncio.sleep(1)  # Небольшая пауза между запросами
    
    # Итоги
    print("\n" + "=" * 60)
    print("📊 Итоги тестирования:")
    for query, success in results:
        status = "✅" if success else "❌"
        print(f"  {status} {query}")
    
    success_count = sum(1 for _, success in results if success)
    print(f"\n✅ Успешно: {success_count}/{len(results)}")
    
    if success_count == len(results):
        print("🎉 Все тесты прошли успешно!")
        return 0
    else:
        print("⚠️  Некоторые тесты не прошли")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
