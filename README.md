📚 Obsidian Indexer Bot

A Telegram bot that lets you search through your Obsidian notes using semantic embeddings.
It indexes your markdown files into a PostgreSQL database, computes embeddings with Ollama
, and performs similarity search.

This project is perfect if you want to turn your Obsidian vault into a searchable knowledge base powered by AI.

✨ Features
- 🔍 Semantic search over your Obsidian markdown notes.
- 🗂️ Splits markdown files by headers (#, ##, ###) for granular indexing.
- ⚡ Embedding generation with Ollama
 (default: llama3.2:3b).
- 🗄️ Stores documents & embeddings in PostgreSQL with pgvector.
- 🤖 Easy-to-use Telegram bot interface powered by aiogram
. 🔄 On-demand reindexing of your notes via /reindex command.

🏗️ Architecture

+-----------------+       +-------------------+       +-------------+
|   Obsidian MD   |  -->  |   ObsidianIndexer |  -->  | PostgreSQL  |
|   Vault files   |       |   (async, aiohttp)|       | + pgvector  |
+-----------------+       +-------------------+       +-------------+
                                 |
                                 v
                           +-----------+
                           |  Ollama   |  (embeddings)
                           +-----------+
                                 |
                                 v
                           +--------------+
                           | Telegram Bot |
                           +--------------+

⚙️ Requirements
+ Python 3.10+
+ PostgreSQL with pgvector extension installed
+ Ollama running locally (default: http://localhost:11434)
+ A Telegram bot token from @BotFather

📦 Installation

Clone the repository and install dependencies:

git clone https://github.com/yourusername/obsidian-indexer-bot.git
cd obsidian-indexer-bot
pip install -r requirements.txt


Dependencies used:

- asyncpg
- aiohttp
- langchain
- aiogram
- numpy
- python-dotenv

🗄️ Database Setup

Enable pgvector in your database:

CREATE EXTENSION IF NOT EXISTS vector;

Create tables:

CREATE TABLE source_documents (
    id SERIAL PRIMARY KEY,
    file_path TEXT UNIQUE NOT NULL,
    file_hash TEXT NOT NULL,
    last_indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE document_chunks (
    id SERIAL PRIMARY KEY,
    source_id INT REFERENCES source_documents(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    embedding vector(4096), -- adjust dimension to match Ollama embedding size
    metadata JSONB
);

🔑 Configuration

Create a .env file with your Telegram bot token:

BOT_TOKEN=your_telegram_bot_token_here

Update the PostgreSQL connection in db_filling.py:

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "postgres",
    "user": "postgres", 
    "password": "your_password"
}


Set your Obsidian vault path:

OBSIDIAN_DIR = "second_brain"

▶️ Usage
Start the bot
python bot.py

Commands

/start → Show welcome message

/help → Show usage instructions

/reindex → Reindex your Obsidian notes

Send any text → Perform semantic search (returns top results)

🔍 Example

Query:

машинное обучение


Bot response:

🎯 Найдено 3 результатов для запроса: машинное обучение

1. ml_notes.md
📊 Релевантность: 92.4%
📝 Текст: Машинное обучение — это раздел искусственного интеллекта...
📁 Путь: second_brain/ml_notes.md

🛠️ Development

Run indexer manually for debugging:

python db_filling.py


This will:

Optionally clear the tables (raw_start)

Index all markdown files

Run a sample search query from the terminal

🚀 Roadmap

 Add Docker support for PostgreSQL + Ollama

 Improve markdown splitting (support lists, code blocks, etc.)

 Add web UI for search in addition to Telegram bot

 Incremental indexing with file system watchers

🤝 Contributing

Contributions are welcome! Feel free to open issues or pull requests.
