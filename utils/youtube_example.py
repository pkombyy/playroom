"""
Примеры использования асинхронной загрузки треков
"""
import asyncio
from utils.youtube import download_track, download_tracks_parallel, get_download_queue


# Пример 1: Простая асинхронная загрузка одного трека
async def example_single_download():
    """Загрузка одного трека"""
    result = await download_track("Never Gonna Give You Up")
    if result:
        print(f"✅ Загружено: {result['title']}")
    else:
        print("❌ Ошибка загрузки")


# Пример 2: Параллельная загрузка нескольких треков
async def example_parallel_download():
    """Параллельная загрузка нескольких треков"""
    queries = [
        "Bohemian Rhapsody",
        "Imagine Dragons Believer",
        "The Weeknd Blinding Lights"
    ]
    
    async def progress_callback(query: str, status: str, completed: int, total: int):
        print(f"[{completed}/{total}] {status}: {query}")
    
    results = await download_tracks_parallel(
        queries,
        max_concurrent=3,
        progress_callback=progress_callback
    )
    
    for query, result in results.items():
        if result:
            print(f"✅ {query}: {result['title']}")
        else:
            print(f"❌ {query}: Ошибка")


# Пример 3: Использование очереди загрузок
async def example_queue_download():
    """Использование очереди для фоновой загрузки"""
    queue = get_download_queue()
    
    # Добавляем треки в очередь
    task_id1 = await queue.add("Never Gonna Give You Up", priority=1)
    task_id2 = await queue.add("Bohemian Rhapsody", priority=2)
    task_id3 = await queue.add("Imagine Dragons Believer", priority=1)
    
    # Получаем результаты (можно делать в разных местах кода)
    result1 = await queue.get_result(task_id1)
    result2 = await queue.get_result(task_id2)
    result3 = await queue.get_result(task_id3)
    
    for result in [result1, result2, result3]:
        if result:
            print(f"✅ {result['title']}")


# Пример 4: Загрузка с обработкой ошибок
async def example_with_error_handling():
    """Загрузка с обработкой ошибок"""
    queries = ["Valid Track", "Invalid Track 12345", "Another Valid Track"]
    
    results = await download_tracks_parallel(queries, max_concurrent=2)
    
    successful = []
    failed = []
    
    for query, result in results.items():
        if result:
            successful.append((query, result['title']))
        else:
            failed.append(query)
    
    print(f"✅ Успешно: {len(successful)}")
    print(f"❌ Ошибок: {len(failed)}")
    
    return successful, failed


if __name__ == "__main__":
    print("Пример 1: Одиночная загрузка")
    asyncio.run(example_single_download())
    
    print("\nПример 2: Параллельная загрузка")
    asyncio.run(example_parallel_download())
    
    print("\nПример 3: Очередь загрузок")
    asyncio.run(example_queue_download())
    
    print("\nПример 4: С обработкой ошибок")
    asyncio.run(example_with_error_handling())
