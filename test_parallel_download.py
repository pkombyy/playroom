#!/usr/bin/env python3
"""
Тестовый скрипт для проверки параллельной загрузки треков
"""
import asyncio
import sys
import time
from utils.youtube import download_tracks_parallel, get_download_queue


async def progress_callback(query: str, status: str, completed: int, total: int):
    """Callback для отслеживания прогресса"""
    status_emoji = {
        "started": "🔄",
        "completed": "✅",
        "failed": "❌",
        "cached": "⚡"
    }
    emoji = status_emoji.get(status, "⏳")
    print(f"{emoji} [{completed}/{total}] {status.upper()}: {query}")


async def test_parallel_download():
    """Тестирует параллельную загрузку нескольких треков"""
    print("🎵 Тестирование параллельной загрузки треков")
    print("=" * 60)
    
    # Тестовые запросы
    test_queries = [
        "Never Gonna Give You Up",
        "Bohemian Rhapsody",
        "Imagine Dragons Believer",
        "The Weeknd Blinding Lights",
        "Dua Lipa Levitating"
    ]
    
    # Если переданы аргументы, используем их
    if len(sys.argv) > 1:
        test_queries = sys.argv[1:]
    
    print(f"📋 Загружаю {len(test_queries)} треков параллельно...\n")
    
    start_time = time.time()
    
    # Параллельная загрузка с callback
    results = await download_tracks_parallel(
        test_queries,
        max_concurrent=3,
        progress_callback=progress_callback
    )
    
    elapsed = time.time() - start_time
    
    # Итоги
    print("\n" + "=" * 60)
    print("📊 Итоги загрузки:")
    print(f"⏱️  Время: {elapsed:.2f} секунд")
    print(f"📈 Скорость: {len(test_queries) / elapsed:.2f} треков/сек\n")
    
    success_count = sum(1 for r in results.values() if r is not None)
    failed_count = len(results) - success_count
    
    for query, result in results.items():
        if result:
            size = len(result["buffer"].getvalue()) / 1024 / 1024
            print(f"✅ {query}: {result['title'][:50]}... ({size:.2f} MB)")
        else:
            print(f"❌ {query}: Ошибка загрузки")
    
    print(f"\n✅ Успешно: {success_count}/{len(test_queries)}")
    if failed_count > 0:
        print(f"❌ Ошибок: {failed_count}/{len(test_queries)}")
    
    return success_count == len(test_queries)


async def test_download_queue():
    """Тестирует очередь загрузок"""
    print("\n" + "=" * 60)
    print("📥 Тестирование очереди загрузок")
    print("=" * 60)
    
    queue = get_download_queue()
    
    queries = [
        "Never Gonna Give You Up",
        "Bohemian Rhapsody",
        "Imagine Dragons Believer"
    ]
    
    print(f"📋 Добавляю {len(queries)} треков в очередь...\n")
    
    task_ids = []
    for query in queries:
        task_id = await queue.add(query)
        task_ids.append((query, task_id))
        print(f"➕ Добавлено в очередь: {query} (ID: {task_id})")
    
    print("\n⏳ Ожидаю завершения загрузок...\n")
    
    start_time = time.time()
    
    # Получаем результаты
    for query, task_id in task_ids:
        result = await queue.get_result(task_id, timeout=300.0)
        if result:
            size = len(result["buffer"].getvalue()) / 1024 / 1024
            print(f"✅ {query}: {result['title'][:50]}... ({size:.2f} MB)")
        else:
            print(f"❌ {query}: Ошибка или таймаут")
    
    elapsed = time.time() - start_time
    print(f"\n⏱️  Время: {elapsed:.2f} секунд")


async def main():
    """Основная функция"""
    # Тест параллельной загрузки
    success = await test_parallel_download()
    
    # Тест очереди
    await test_download_queue()
    
    if success:
        print("\n🎉 Все тесты прошли успешно!")
        return 0
    else:
        print("\n⚠️  Некоторые тесты не прошли")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
