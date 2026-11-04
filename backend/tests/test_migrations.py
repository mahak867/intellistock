"""The schema migrations must exist, form one chain, and match the models."""
import os

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _cfg():
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "infra", "docker", "migrations"))
    return cfg


def test_one_linear_migration_chain():
    sd = ScriptDirectory.from_config(_cfg())
    assert len(sd.get_heads()) == 1
    assert sd.get_current_head() is not None


@pytest.mark.skipif(not os.environ.get("MIGRATION_TEST_DB_URL"), reason="set MIGRATION_TEST_DB_URL to an empty Postgres database (postgresql+asyncpg://...) to run")
def test_upgrade_matches_models():
    from alembic import command

    cfg = _cfg()
    os.environ["DATABASE_URL"] = os.environ["MIGRATION_TEST_DB_URL"]
    command.upgrade(cfg, "head")
    command.check(cfg)  # raises if the models have drifted from the migrations
