import os

# 必须在 import app.* 之前：config 在导入时读取环境变量。
# 测试本身不使用该引擎（fixture 另建临时文件库），这里仅保证 app 可导入、lifespan 不连 Postgres。
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SEED_ON_EMPTY"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def Session_(tmp_path):
    # TestClient 的请求在独立线程执行：必须用 NullPool，避免连接跨线程复用
    # 触发 SQLite 的线程亲和性错误（那会在封场等写路径上表现为偶发路由级 404）。
    eng = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        poolclass=NullPool,
    )
    Base.metadata.create_all(eng)
    yield sessionmaker(bind=eng, autoflush=False, autocommit=False)
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def client(Session_):
    def _override():
        s = Session_()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    # 用 with 触发 lifespan，使中间件/路由栈在首个请求前完成构建。
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
