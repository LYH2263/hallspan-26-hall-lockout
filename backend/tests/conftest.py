import os

# 测试不依赖 Postgres：在 app 任何模块导入前把数据库指到内存 SQLite
os.environ.setdefault("DATABASE_URL", "sqlite://")
