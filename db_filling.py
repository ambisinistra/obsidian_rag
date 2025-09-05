import asyncio
import asyncpg
import os
import hashlib
import json
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import aiohttp
from langchain.text_splitter import MarkdownHeaderTextSplitter

class ObsidianIndexer:
    def __init__(self, 
                 obsidian_dir: str,
                 db_config: Dict[str, str],
                 ollama_url: str = "http://localhost:11434",
                 model_name: str = "llama3.2:3b"):
        self.obsidian_dir = Path(obsidian_dir)
        self.db_config = db_config
        self.ollama_url = ollama_url
        self.model_name = model_name
        
        # Настройка сплиттера для Markdown
        headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"), 
            ("###", "Header 3"),
        ]
        self.markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=True,
            return_each_line=False
        )
        
    def calculate_file_hash(self, file_path: Path) -> str:
        """Вычисляет SHA-256 хеш файла"""
        hash_sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    
    def get_markdown_files(self) -> List[Path]:
        """Получает все .md файлы из директории Obsidian"""
        return list(self.obsidian_dir.rglob("*.md"))
    
    async def get_embedding(self, text: str) -> List[float]:
        """Получает эмбеддинг от Ollama"""
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": self.model_name,
                "prompt": text
            }
            
            async with session.post(
                f"{self.ollama_url}/api/embeddings", 
                json=payload
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result["embedding"]
                else:
                    error_text = await response.text()
                    raise Exception(f"Ошибка получения эмбеддинга: {error_text}")
    
    async def process_markdown_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Обрабатывает markdown файл и возвращает чанки с метаданными"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            print(f"Ошибка чтения файла {file_path}: неверная кодировка")
            return []
        
        if not content.strip():
            return []
        
        # Разбиваем документ на чанки по заголовкам
        chunks = self.markdown_splitter.split_text(content)
        
        processed_chunks = []
        for i, chunk in enumerate(chunks):
            chunk_text = chunk.page_content.strip()
            if not chunk_text:
                continue
                
            # Извлекаем метаданные из заголовков
            metadata = {
                "file_name": file_path.name,
                "chunk_index": i,
                "headers": chunk.metadata,
                "file_path": str(file_path.relative_to(self.obsidian_dir))
            }
            
            processed_chunks.append({
                "text": chunk_text,
                "metadata": metadata
            })
        
        return processed_chunks
    
    async def check_file_needs_update(self, conn: asyncpg.Connection, 
                                    file_path: Path, file_hash: str) -> bool:
        """Проверяет, нужно ли обновлять файл в базе данных"""
        relative_path = str(file_path.relative_to(self.obsidian_dir))
        
        result = await conn.fetchrow(
            "SELECT file_hash FROM source_documents WHERE file_path = $1",
            relative_path
        )
        
        if result is None:
            return True  # Файл не найден, нужно добавить
        
        return result['file_hash'] != file_hash  # Нужно обновить если хеш изменился
    
    async def update_source_document(self, conn: asyncpg.Connection, 
                                   file_path: Path, file_hash: str) -> int:
        """Обновляет или создает запись в source_documents"""
        relative_path = str(file_path.relative_to(self.obsidian_dir))
        
        # Проверяем, существует ли документ
        existing = await conn.fetchrow(
            "SELECT id FROM source_documents WHERE file_path = $1",
            relative_path
        )
        
        if existing:
            # Обновляем существующий документ
            await conn.execute(
                """UPDATE source_documents 
                   SET file_hash = $1, last_indexed_at = CURRENT_TIMESTAMP 
                   WHERE file_path = $2""",
                file_hash, relative_path
            )
            
            # Удаляем старые чанки
            await conn.execute(
                "DELETE FROM document_chunks WHERE source_id = $1",
                existing['id']
            )
            
            return existing['id']
        else:
            # Создаем новый документ
            result = await conn.fetchrow(
                """INSERT INTO source_documents (file_path, file_hash) 
                   VALUES ($1, $2) RETURNING id""",
                relative_path, file_hash
            )
            return result['id']
    
    async def insert_chunks(self, conn: asyncpg.Connection, 
                          source_id: int, chunks: List[Dict[str, Any]]):
        """Вставляет чанки документа в базу данных"""
        for chunk in chunks:
            try:
                # Получаем эмбеддинг для текста
                embedding = await self.get_embedding(chunk["text"])
                #print (np.linalg.norm(embedding))
                embedding /= np.linalg.norm(embedding)
                #print (np.linalg.norm(embedding))
                vec_str = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
                
                # Вставляем чанк
                await conn.execute(
                    """INSERT INTO document_chunks (source_id, chunk_text, embedding, metadata)
                       VALUES ($1, $2, $3, $4)""",
                    source_id,
                    chunk["text"],
                    vec_str,
                    json.dumps(chunk["metadata"])
                )
                
            except Exception as e:
                print(f"Ошибка при обработке чанка: {e}")
                continue
    
    async def index_file(self, conn: asyncpg.Connection, file_path: Path):
        """Индексирует один файл"""
        try:
            file_hash = self.calculate_file_hash(file_path)
            
            # Проверяем, нужно ли обновлять файл
            if not await self.check_file_needs_update(conn, file_path, file_hash):
                print(f"Файл {file_path.name} уже актуален, пропускаем")
                return
            
            print(f"Обрабатываем файл: {file_path.name}")
            
            # Обрабатываем markdown файл
            chunks = await self.process_markdown_file(file_path)
            
            if not chunks:
                print(f"Нет чанков для файла {file_path.name}")
                return
            
            # Обновляем source_document
            source_id = await self.update_source_document(conn, file_path, file_hash)
            
            # Вставляем чанки
            await self.insert_chunks(conn, source_id, chunks)
            
            print(f"Файл {file_path.name} проиндексирован: {len(chunks)} чанков")
            
        except Exception as e:
            print(f"Ошибка при индексации файла {file_path}: {e}")
    
    async def index_all_files(self):
        """Индексирует все файлы в директории Obsidian"""
        # Подключение к базе данных
        conn = await asyncpg.connect(**self.db_config)
        
        try:
            # Получаем все markdown файлы
            markdown_files = self.get_markdown_files()
            print(f"Найдено {len(markdown_files)} markdown файлов")
            
            # Обрабатываем файлы последовательно (чтобы не перегружать Ollama)
            for file_path in markdown_files:
                await self.index_file(conn, file_path)
                
        finally:
            await conn.close()
    
    async def raw_start(self):
        """Очищает все таблицы (удаляет всё содержимое source_documents и document_chunks)"""
        conn = await asyncpg.connect(**self.db_config)
        
        try:
            print("Очищаем таблицы...")
            
            # Удаляем все чанки (сначала дочернюю таблицу из-за foreign key)
            await conn.execute("DELETE FROM document_chunks")
            print("Таблица document_chunks очищена")
            
            # Удаляем все документы
            await conn.execute("DELETE FROM source_documents")
            print("Таблица source_documents очищена")
            
            # Сбрасываем последовательности (автоинкременты) к начальному значению
            await conn.execute("ALTER SEQUENCE source_documents_id_seq RESTART WITH 1")
            await conn.execute("ALTER SEQUENCE document_chunks_id_seq RESTART WITH 1")
            print("Последовательности ID сброшены")
            
            print("Все таблицы успешно очищены!")
            
        except Exception as e:
            print(f"Ошибка при очистке таблиц: {e}")
            raise
        finally:
            await conn.close()
    
    async def search_similar(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Поиск похожих документов по запросу"""
        conn = await asyncpg.connect(**self.db_config)
        
        try:
            # Получаем эмбеддинг для запроса
            query_embedding = await self.get_embedding(query)
            query_embedding /= np.linalg.norm(query_embedding)
            query_vec_str = "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]"
            
            # Выполняем векторный поиск
            results = await conn.fetch(
                """
                SELECT 
                    dc.chunk_text,
                    dc.metadata,
                    sd.file_path,
                    dc.embedding <-> $1 as distance
                FROM document_chunks dc
                JOIN source_documents sd ON dc.source_id = sd.id
                ORDER BY dc.embedding <-> $1
                LIMIT $2
                """,
                query_vec_str, limit
            )

            #print (query_embedding)
            #print ()
            #print (query_vec_str)
            
            return [
                {
                    "text": row["chunk_text"],
                    "metadata": json.loads(row["metadata"]),
                    "file_path": row["file_path"],
                    "distance": float(row["distance"])
                }
                for row in results
            ]
            
        finally:
            await conn.close()

# Конфигурация
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "postgres",
    "user": "postgres", 
    "password": "tr134sdfWE"
}

async def main():
    """Основная функция"""
    indexer = ObsidianIndexer(
        obsidian_dir="./second_brain",  # Путь к вашей директории с заметками
        db_config=DB_CONFIG
    )
    
    # Раскомментируйте эту строку, если хотите начать с чистых таблиц
    await indexer.raw_start()
    
    print("Начинаем индексацию заметок Obsidian...")
    await indexer.index_all_files()
    print("Индексация завершена!")
    
    # Пример поиска
    print("\nПример поиска:")
    input_query = input("Введи поисковой запрос\n")
    results = await indexer.search_similar(input_query, limit=3)
    for i, result in enumerate(results, 1):
        print(f"\n{i}. Файл: {result['file_path']}")
        print(f"   Расстояние: {result['distance']:.4f}")
        print(f"   Текст: {result['text'][:200]}...")

if __name__ == "__main__":
    # Установка необходимых пакетов:
    # pip install asyncpg aiohttp langchain
    
    asyncio.run(main())