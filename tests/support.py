import sys
import types


def ensure_test_stubs():
    if "loguru" not in sys.modules:
        class _FakeLogger:
            def info(self, *args, **kwargs):
                return None

            def warning(self, *args, **kwargs):
                return None

            def error(self, *args, **kwargs):
                return None

            def remove(self, *args, **kwargs):
                return None

            def add(self, *args, **kwargs):
                return None

            def patch(self, *args, **kwargs):
                return self

        loguru_module = types.ModuleType("loguru")
        loguru_module.logger = _FakeLogger()
        sys.modules["loguru"] = loguru_module

    if "sqlalchemy" not in sys.modules:
        sqlalchemy_module = types.ModuleType("sqlalchemy")
        sqlalchemy_module.text = lambda value: value
        sqlalchemy_module.String = type("String", (), {})
        sqlalchemy_module.Text = type("Text", (), {})

        sqlalchemy_ext_module = types.ModuleType("sqlalchemy.ext")
        sqlalchemy_asyncio_module = types.ModuleType("sqlalchemy.ext.asyncio")

        class _AsyncEngine:
            async def dispose(self):
                return None

        class _AsyncSession:
            pass

        def _async_sessionmaker(*args, **kwargs):
            return None

        def _create_async_engine(*args, **kwargs):
            return _AsyncEngine()

        sqlalchemy_asyncio_module.AsyncEngine = _AsyncEngine
        sqlalchemy_asyncio_module.AsyncSession = _AsyncSession
        sqlalchemy_asyncio_module.async_sessionmaker = _async_sessionmaker
        sqlalchemy_asyncio_module.create_async_engine = _create_async_engine

        sys.modules["sqlalchemy"] = sqlalchemy_module
        sys.modules["sqlalchemy.ext"] = sqlalchemy_ext_module
        sys.modules["sqlalchemy.ext.asyncio"] = sqlalchemy_asyncio_module
