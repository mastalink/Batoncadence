"""Migration runner: discovery, drift guard, Postgres apply, manual fallback."""

from pathlib import Path

import mco.migrations_runner as mig


def test_discover_returns_sorted_sql():
    migs = mig.discover()
    names = [n for n, _ in migs]
    assert names == sorted(names)
    assert all(n.endswith(".sql") for n in names)
    assert any("governance" in n for n in names)


def test_packaged_copy_matches_authored_docs():
    """Drift guard: src/mco/migrations must mirror docs/migrations byte-for-byte,
    so wheel installs ship exactly what the docs describe."""
    docs = Path(__file__).resolve().parents[1] / "docs" / "migrations"
    pkg = Path(mig.__file__).resolve().parent / "migrations"
    if not docs.is_dir() or not pkg.is_dir():
        return  # nothing to compare in this layout
    docs_files = {p.name: p.read_text(encoding="utf-8") for p in docs.glob("*.sql")}
    pkg_files = {p.name: p.read_text(encoding="utf-8") for p in pkg.glob("*.sql")}
    assert docs_files.keys() == pkg_files.keys(), "migration file sets differ"
    for name in docs_files:
        assert docs_files[name] == pkg_files[name], f"{name} differs between docs and package"


def test_migrations_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MCO_MIGRATIONS_DIR", str(tmp_path))
    (tmp_path / "001_x.sql").write_text("create table if not exists x (id int);")
    assert mig.migrations_dir() == tmp_path
    assert mig.discover() == [("001_x.sql", "create table if not exists x (id int);")]


def test_write_combined_script_lists_pending(monkeypatch, tmp_path):
    monkeypatch.setenv("MCO_MIGRATIONS_DIR", str(tmp_path))
    (tmp_path / "a.sql").write_text("-- a")
    (tmp_path / "b.sql").write_text("-- b")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    out, pending = mig.write_combined_script(applied_names={"a.sql"})
    assert pending == ["b.sql"]                      # 'a' already applied, excluded
    text = out.read_text()
    assert "b.sql" in text and "-- b" in text
    assert "a.sql" not in text


class FakeCursor:
    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        self.store["log"].append((sql, params))
        if sql.startswith("SELECT name"):
            self._rows = [(n,) for n in self.store["applied"]]

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.store["commits"] += 1

    def rollback(self):
        self.store["rollbacks"] += 1

    def close(self):
        self.store["closed"] = True


def test_apply_postgres_skips_done_applies_pending(monkeypatch):
    store = {"log": [], "applied": ["2026-06_multi_tenancy.sql"],
             "commits": 0, "rollbacks": 0, "closed": False}
    monkeypatch.setattr(mig, "_connect", lambda url: (FakeConn(store), "psycopg"))
    result = mig.apply_postgres("postgres://x")
    assert "2026-06_multi_tenancy.sql" in result["skipped"]
    assert "2026-06_phase_a_governance.sql" in result["applied"]
    # Each applied migration is recorded in schema_migrations.
    inserts = [s for s, p in store["log"] if s.startswith("INSERT INTO schema_migrations")]
    assert len(inserts) == len(result["applied"])
    assert store["closed"] is True


def test_apply_postgres_without_driver_is_clear(monkeypatch):
    monkeypatch.setattr(mig, "_connect", lambda url: (None, None))
    try:
        mig.apply_postgres("postgres://x")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "psycopg" in str(e)
