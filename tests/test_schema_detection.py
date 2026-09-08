"""Comprehensive tests for schema auto-detection and tiered database setup.

Covers all 5 tiers, edge cases, and detection rules using temporary directory fixtures.
"""
import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from automation.domain.schema_detection import (
    DatabaseType,
    MigrationFramework,
    ORMFramework,
    SchemaSourceTier,
)
from automation.services.schema_detection_service import SchemaDetectionService


def _create_file(base: Path, relative: str, content: str = "") -> Path:
    """Helper: create a file with optional content under a base directory."""
    path = base / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestTier1MigrationDetection(unittest.TestCase):
    """Tier 1: Migration framework detection tests."""

    def setUp(self) -> None:
        self.svc = SchemaDetectionService()
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_alembic_detected_from_ini_and_versions(self) -> None:
        """Alembic detected when alembic.ini and versions directory exist."""
        _create_file(self.repo, "alembic.ini", "[alembic]\nscript_location = alembic")
        _create_file(self.repo, "alembic/env.py", "from alembic import context")
        _create_file(self.repo, "alembic/versions/001_init.py", "# migration")

        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.MIGRATIONS)
        self.assertEqual(len(result.migrations), 1)
        self.assertEqual(result.migrations[0].framework, MigrationFramework.ALEMBIC)
        self.assertIn("alembic upgrade head", result.migrations[0].setup_command)
        self.assertIn("alembic.ini", result.migrations[0].marker_files)

    def test_django_detected_with_manage_py_and_migrations(self) -> None:
        """Django detected only when BOTH manage.py AND migration files exist."""
        _create_file(self.repo, "manage.py", "#!/usr/bin/env python\nimport django")
        _create_file(self.repo, "myapp/migrations/__init__.py", "")
        _create_file(self.repo, "myapp/migrations/0001_initial.py", "# migration")

        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.MIGRATIONS)
        frameworks = [m.framework for m in result.migrations]
        self.assertIn(MigrationFramework.DJANGO, frameworks)

    def test_django_not_detected_with_manage_py_alone(self) -> None:
        """manage.py alone is NOT enough — must also have migration files."""
        _create_file(self.repo, "manage.py", "#!/usr/bin/env python")

        result = self.svc.detect(self.repo)

        frameworks = [m.framework for m in result.migrations]
        self.assertNotIn(MigrationFramework.DJANGO, frameworks)

    def test_prisma_detected(self) -> None:
        """Prisma detected from schema.prisma file."""
        _create_file(self.repo, "prisma/schema.prisma", textwrap.dedent("""\
            datasource db {
              provider = "postgresql"
              url      = env("DATABASE_URL")
            }
            model User {
              id Int @id @default(autoincrement())
            }
        """))

        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.MIGRATIONS)
        self.assertEqual(result.migrations[0].framework, MigrationFramework.PRISMA)

    def test_knex_detected_from_knexfile(self) -> None:
        """Knex detected from knexfile.js."""
        _create_file(self.repo, "knexfile.js", "module.exports = { client: 'pg' };")
        _create_file(self.repo, "migrations/20240101_create_users.js", "// migration")

        result = self.svc.detect(self.repo)

        frameworks = [m.framework for m in result.migrations]
        self.assertIn(MigrationFramework.KNEX, frameworks)

    def test_rails_detected(self) -> None:
        """Rails detected from Rakefile and db/migrate."""
        _create_file(self.repo, "Rakefile", "require 'rails'")
        _create_file(self.repo, "config/database.yml", "default: &default\n  adapter: postgresql")
        _create_file(self.repo, "db/migrate/20240101_create_users.rb", "class CreateUsers < ActiveRecord::Migration")

        result = self.svc.detect(self.repo)

        frameworks = [m.framework for m in result.migrations]
        self.assertIn(MigrationFramework.RAILS, frameworks)

    def test_diesel_detected(self) -> None:
        """Diesel detected from diesel.toml and migration files."""
        _create_file(self.repo, "diesel.toml", "[print_schema]\nfile = \"src/schema.rs\"")
        _create_file(self.repo, "migrations/2024-01-01/up.sql", "CREATE TABLE users;")
        _create_file(self.repo, "migrations/2024-01-01/down.sql", "DROP TABLE users;")

        result = self.svc.detect(self.repo)

        frameworks = [m.framework for m in result.migrations]
        self.assertIn(MigrationFramework.DIESEL, frameworks)

    def test_flyway_detected(self) -> None:
        """Flyway detected from flyway.conf."""
        _create_file(self.repo, "flyway.conf", "flyway.url=jdbc:postgresql://localhost/db")

        result = self.svc.detect(self.repo)

        frameworks = [m.framework for m in result.migrations]
        self.assertIn(MigrationFramework.FLYWAY, frameworks)

    def test_multiple_frameworks_generates_warning(self) -> None:
        """Multiple migration frameworks detected produces a warning."""
        _create_file(self.repo, "alembic.ini", "[alembic]")
        _create_file(self.repo, "alembic/env.py", "")
        _create_file(self.repo, "prisma/schema.prisma", "datasource db { provider = 'pg' }")

        result = self.svc.detect(self.repo)

        self.assertGreater(len(result.migrations), 1)
        self.assertTrue(any("Multiple migration frameworks" in w for w in result.warnings))


class TestTier2ORMDetection(unittest.TestCase):
    """Tier 2: ORM framework detection tests."""

    def setUp(self) -> None:
        self.svc = SchemaDetectionService()
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_sqlalchemy_detected_from_declarative_base(self) -> None:
        """SQLAlchemy detected from declarative_base() usage."""
        _create_file(self.repo, "app/models.py", textwrap.dedent("""\
            from sqlalchemy.orm import declarative_base
            Base = declarative_base()
            class User(Base):
                __tablename__ = 'users'
        """))

        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.ORM_MODELS)
        self.assertEqual(result.orm_models[0].framework, ORMFramework.SQLALCHEMY)
        self.assertIn("app/models.py", result.orm_models[0].marker_files)

    def test_sqlalchemy_detected_from_mapped_column(self) -> None:
        """SQLAlchemy 2.0 detected from mapped_column() usage."""
        _create_file(self.repo, "models/user.py", textwrap.dedent("""\
            from sqlalchemy.orm import DeclarativeBase, mapped_column
            class Base(DeclarativeBase):
                pass
            class User(Base):
                id = mapped_column(Integer, primary_key=True)
        """))

        result = self.svc.detect(self.repo)

        orm_frameworks = [o.framework for o in result.orm_models]
        self.assertIn(ORMFramework.SQLALCHEMY, orm_frameworks)

    def test_django_orm_detected_from_models(self) -> None:
        """Django ORM detected from models.Model inheritance."""
        _create_file(self.repo, "blog/models.py", textwrap.dedent("""\
            from django.db import models
            class Post(models.Model):
                title = models.CharField(max_length=200)
        """))

        result = self.svc.detect(self.repo)

        orm_frameworks = [o.framework for o in result.orm_models]
        self.assertIn(ORMFramework.DJANGO_ORM, orm_frameworks)

    def test_prisma_orm_detected_from_schema(self) -> None:
        """Prisma ORM detected from .prisma schema model definitions."""
        _create_file(self.repo, "prisma/schema.prisma", textwrap.dedent("""\
            datasource db {
              provider = "postgresql"
            }
            model User {
              id Int @id
            }
        """))

        result = self.svc.detect(self.repo)

        orm_frameworks = [o.framework for o in result.orm_models]
        self.assertIn(ORMFramework.PRISMA_ORM, orm_frameworks)

    def test_typeorm_detected_from_entity_decorator(self) -> None:
        """TypeORM detected from @Entity() decorator in TypeScript."""
        _create_file(self.repo, "src/entity/User.ts", textwrap.dedent("""\
            import { Entity, Column } from 'typeorm';
            @Entity()
            export class User {
              @Column()
              name: string;
            }
        """))

        result = self.svc.detect(self.repo)

        orm_frameworks = [o.framework for o in result.orm_models]
        self.assertIn(ORMFramework.TYPEORM_ORM, orm_frameworks)

    def test_orm_only_generates_incomplete_schema_warning(self) -> None:
        """ORM-only detection produces a warning about missing triggers/views."""
        _create_file(self.repo, "app/models.py", textwrap.dedent("""\
            from sqlalchemy.orm import declarative_base
            Base = declarative_base()
        """))

        result = self.svc.detect(self.repo)

        self.assertTrue(any("triggers" in w for w in result.warnings))


class TestTier3SchemaFileDetection(unittest.TestCase):
    """Tier 3: Committed schema file detection tests."""

    def setUp(self) -> None:
        self.svc = SchemaDetectionService()
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_schema_sql_detected(self) -> None:
        """schema.sql in repo root is detected."""
        _create_file(self.repo, "schema.sql", "CREATE TABLE users (id SERIAL PRIMARY KEY);")

        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.SCHEMA_FILES)
        self.assertEqual(len(result.schema_files), 1)
        self.assertEqual(result.schema_files[0].path, "schema.sql")
        self.assertEqual(result.schema_files[0].database_type, DatabaseType.POSTGRESQL)

    def test_db_seed_sql_detected(self) -> None:
        """db/seed.sql is detected."""
        _create_file(self.repo, "db/seed.sql", "INSERT INTO config VALUES ('key', 'val');")

        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.SCHEMA_FILES)
        self.assertEqual(result.schema_files[0].path, "db/seed.sql")

    def test_mysql_syntax_inferred(self) -> None:
        """MySQL-specific syntax is correctly identified."""
        _create_file(self.repo, "schema.sql", textwrap.dedent("""\
            CREATE TABLE users (
              id INT AUTO_INCREMENT PRIMARY KEY,
              name VARCHAR(100)
            ) ENGINE=InnoDB;
        """))

        result = self.svc.detect(self.repo)

        self.assertEqual(result.schema_files[0].database_type, DatabaseType.MYSQL)

    def test_multiple_schema_files(self) -> None:
        """Multiple schema files in different locations are all detected."""
        _create_file(self.repo, "schema.sql", "CREATE TABLE a (id SERIAL);")
        _create_file(self.repo, "db/init.sql", "CREATE TABLE b (id SERIAL);")
        _create_file(self.repo, "seed.sql", "INSERT INTO a VALUES (1);")

        result = self.svc.detect(self.repo)

        self.assertGreaterEqual(len(result.schema_files), 3)

    def test_setup_commands_for_postgresql_schema(self) -> None:
        """Setup commands use psql for PostgreSQL schema files."""
        _create_file(self.repo, "db/schema.sql", "CREATE TABLE users (id SERIAL PRIMARY KEY);")

        result = self.svc.detect(self.repo)

        self.assertTrue(any("psql" in cmd for cmd in result.setup_commands))


class TestTier4DockerComposeDetection(unittest.TestCase):
    """Tier 4: Docker Compose service detection tests."""

    def setUp(self) -> None:
        self.svc = SchemaDetectionService()
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_docker_compose_postgres_and_redis(self) -> None:
        """Detects PostgreSQL and Redis services from docker-compose.yml."""
        _create_file(self.repo, "docker-compose.yml", textwrap.dedent("""\
            version: '3.8'
            services:
              postgres:
                image: postgres:16
                ports:
                  - "5432:5432"
                environment:
                  POSTGRES_DB: mydb
                  POSTGRES_USER: admin
              redis:
                image: redis:7
                ports:
                  - "6379:6379"
        """))

        result = self.svc.detect(self.repo)

        self.assertEqual(len(result.docker_services), 2)
        db_types = {ds.database_type for ds in result.docker_services}
        self.assertIn(DatabaseType.POSTGRESQL, db_types)
        self.assertIn(DatabaseType.REDIS, db_types)

        pg_svc = next(ds for ds in result.docker_services if ds.database_type == DatabaseType.POSTGRESQL)
        self.assertEqual(pg_svc.image, "postgres:16")
        self.assertIn("5432:5432", pg_svc.ports)
        self.assertEqual(pg_svc.environment.get("POSTGRES_DB"), "mydb")

    def test_compose_yaml_variant_detected(self) -> None:
        """compose.yaml (modern format) is also detected."""
        _create_file(self.repo, "compose.yaml", textwrap.dedent("""\
            services:
              db:
                image: mysql:8
                ports:
                  - "3306:3306"
        """))

        result = self.svc.detect(self.repo)

        self.assertEqual(len(result.docker_services), 1)
        self.assertEqual(result.docker_services[0].database_type, DatabaseType.MYSQL)

    def test_typesense_image_mapped_correctly(self) -> None:
        """typesense/typesense image maps to TYPESENSE database type."""
        _create_file(self.repo, "docker-compose.yml", textwrap.dedent("""\
            services:
              search:
                image: typesense/typesense:27.1
                ports:
                  - "8108:8108"
        """))

        result = self.svc.detect(self.repo)

        self.assertEqual(result.docker_services[0].database_type, DatabaseType.TYPESENSE)

    def test_docker_compose_only_is_tier_4(self) -> None:
        """When only docker-compose exists (no migrations/ORM/schema), resolves to Tier 4."""
        _create_file(self.repo, "docker-compose.yml", textwrap.dedent("""\
            services:
              postgres:
                image: postgres:16
                ports:
                  - "5432:5432"
        """))

        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.DOCKER_COMPOSE)
        self.assertTrue(any("docker compose" in cmd for cmd in result.setup_commands))


class TestDatabaseDependencyDetection(unittest.TestCase):
    """Database detection from dependency manifest files."""

    def setUp(self) -> None:
        self.svc = SchemaDetectionService()
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_python_requirements_txt(self) -> None:
        """Detects databases from requirements.txt."""
        _create_file(self.repo, "requirements.txt", textwrap.dedent("""\
            flask==2.3.0
            psycopg2-binary>=2.9
            redis~=4.5
            pymongo==4.6.1
        """))

        result = self.svc.detect(self.repo)

        db_types = {d.database_type for d in result.databases}
        self.assertIn(DatabaseType.POSTGRESQL, db_types)
        self.assertIn(DatabaseType.REDIS, db_types)
        self.assertIn(DatabaseType.MONGODB, db_types)

    def test_node_package_json(self) -> None:
        """Detects databases from package.json."""
        _create_file(self.repo, "package.json", json.dumps({
            "name": "myapp",
            "dependencies": {
                "pg": "^8.11",
                "ioredis": "^5.3",
                "@elastic/elasticsearch": "^8.12",
            },
        }))

        result = self.svc.detect(self.repo)

        db_types = {d.database_type for d in result.databases}
        self.assertIn(DatabaseType.POSTGRESQL, db_types)
        self.assertIn(DatabaseType.REDIS, db_types)
        self.assertIn(DatabaseType.ELASTICSEARCH, db_types)

    def test_pyproject_toml_with_extras(self) -> None:
        """Detects databases from pyproject.toml with extras syntax like psycopg[binary,pool]."""
        _create_file(self.repo, "pyproject.toml", textwrap.dedent("""\
            [project]
            name = "myapp"
            dependencies = [
                "psycopg2-binary~=2.9.9",
                "psycopg[binary,pool]~=3.2.9",
                "redis~=5.0",
                "typesense==1.1.1",
                "azure-cosmos~=4.7",
            ]
        """))

        result = self.svc.detect(self.repo)

        db_types = {d.database_type for d in result.databases}
        self.assertIn(DatabaseType.POSTGRESQL, db_types)
        self.assertIn(DatabaseType.REDIS, db_types)
        self.assertIn(DatabaseType.TYPESENSE, db_types)
        self.assertIn(DatabaseType.COSMOS_DB, db_types)

    def test_ruby_gemfile(self) -> None:
        """Detects databases from Gemfile."""
        _create_file(self.repo, "Gemfile", textwrap.dedent("""\
            source 'https://rubygems.org'
            gem 'rails', '~> 7.0'
            gem 'pg', '~> 1.5'
            gem 'redis', '~> 5.0'
        """))

        result = self.svc.detect(self.repo)

        db_types = {d.database_type for d in result.databases}
        self.assertIn(DatabaseType.POSTGRESQL, db_types)
        self.assertIn(DatabaseType.REDIS, db_types)

    def test_go_mod(self) -> None:
        """Detects databases from go.mod."""
        _create_file(self.repo, "go.mod", textwrap.dedent("""\
            module github.com/myorg/myapp

            go 1.21

            require (
                github.com/lib/pq v1.10.9
                github.com/redis/go-redis/v9 v9.4.0
            )
        """))

        result = self.svc.detect(self.repo)

        db_types = {d.database_type for d in result.databases}
        self.assertIn(DatabaseType.POSTGRESQL, db_types)
        self.assertIn(DatabaseType.REDIS, db_types)

    def test_cosmos_db_warning_generated(self) -> None:
        """Cosmos DB detection generates a warning about no local emulator."""
        _create_file(self.repo, "requirements.txt", "azure-cosmos~=4.7")

        result = self.svc.detect(self.repo)

        self.assertTrue(any("Cosmos DB" in w for w in result.warnings))

    def test_schemaless_databases_flagged(self) -> None:
        """Redis and MongoDB are correctly flagged as schemaless."""
        _create_file(self.repo, "requirements.txt", "redis~=5.0\npymongo~=4.6")

        result = self.svc.detect(self.repo)

        for db in result.databases:
            if db.database_type in (DatabaseType.REDIS, DatabaseType.MONGODB):
                self.assertTrue(db.is_schemaless)


class TestTier5NoneFound(unittest.TestCase):
    """Tier 5: No schema source found."""

    def setUp(self) -> None:
        self.svc = SchemaDetectionService()
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_repo_is_tier_5(self) -> None:
        """Empty repo resolves to Tier 5."""
        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.NONE_FOUND)
        self.assertTrue(any("No databases" in w for w in result.warnings))

    def test_databases_without_schema_generates_actionable_warning(self) -> None:
        """Databases detected but no schema source produces actionable warning."""
        _create_file(self.repo, "requirements.txt", "psycopg2-binary>=2.9")

        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.NONE_FOUND)
        self.assertTrue(any("pg_dump" in w for w in result.warnings))

    def test_setup_commands_include_instructions(self) -> None:
        """Tier 5 setup commands include human-readable instructions."""
        result = self.svc.detect(self.repo)

        self.assertTrue(any("schema.sql" in cmd for cmd in result.setup_commands))


class TestTierResolutionPriority(unittest.TestCase):
    """Verifies that tier resolution follows strict priority order."""

    def setUp(self) -> None:
        self.svc = SchemaDetectionService()
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_migrations_take_priority_over_orm(self) -> None:
        """Tier 1 (migrations) beats Tier 2 (ORM) when both exist."""
        # ORM models
        _create_file(self.repo, "app/models.py", textwrap.dedent("""\
            from sqlalchemy.orm import declarative_base
            Base = declarative_base()
        """))
        # Alembic migrations
        _create_file(self.repo, "alembic.ini", "[alembic]")
        _create_file(self.repo, "alembic/env.py", "")

        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.MIGRATIONS)

    def test_migrations_take_priority_over_schema_files(self) -> None:
        """Tier 1 (migrations) beats Tier 3 (schema files) when both exist."""
        _create_file(self.repo, "alembic.ini", "[alembic]")
        _create_file(self.repo, "alembic/env.py", "")
        _create_file(self.repo, "schema.sql", "CREATE TABLE users (id SERIAL);")

        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.MIGRATIONS)

    def test_orm_takes_priority_over_schema_files(self) -> None:
        """Tier 2 (ORM) beats Tier 3 (schema files) when both exist."""
        _create_file(self.repo, "app/models.py", textwrap.dedent("""\
            from sqlalchemy.orm import declarative_base
            Base = declarative_base()
        """))
        _create_file(self.repo, "schema.sql", "CREATE TABLE users (id SERIAL);")

        result = self.svc.detect(self.repo)

        self.assertEqual(result.resolved_tier, SchemaSourceTier.ORM_MODELS)


class TestEdgeCases(unittest.TestCase):
    """Edge case tests."""

    def setUp(self) -> None:
        self.svc = SchemaDetectionService()
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_nonexistent_repo_raises_error(self) -> None:
        """Passing a non-existent directory raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            self.svc.detect(Path("/tmp/does_not_exist_xyz123"))

    def test_node_modules_excluded_from_orm_scan(self) -> None:
        """Files in node_modules/ are excluded from ORM scanning."""
        # Put SQLAlchemy code inside node_modules — should NOT be detected
        _create_file(self.repo, "node_modules/pkg/models.py", textwrap.dedent("""\
            from sqlalchemy.orm import declarative_base
            Base = declarative_base()
        """))

        result = self.svc.detect(self.repo)

        self.assertEqual(len(result.orm_models), 0)

    def test_docker_merge_adds_databases_not_in_deps(self) -> None:
        """Databases found in docker-compose but NOT in dependency files are still detected."""
        _create_file(self.repo, "docker-compose.yml", textwrap.dedent("""\
            services:
              redis:
                image: redis:7
                ports:
                  - "6379:6379"
        """))
        # No requirements.txt or package.json — Redis only from docker-compose

        result = self.svc.detect(self.repo)

        db_types = {d.database_type for d in result.databases}
        self.assertIn(DatabaseType.REDIS, db_types)
        # Verify source is docker-compose
        redis_db = next(d for d in result.databases if d.database_type == DatabaseType.REDIS)
        self.assertIn("docker-compose", redis_db.detection_source)

    def test_pipfile_dependencies_parsed(self) -> None:
        """Pipfile package names are correctly extracted."""
        _create_file(self.repo, "Pipfile", textwrap.dedent("""\
            [packages]
            psycopg2-binary = "~=2.9"
            redis = "*"

            [dev-packages]
            pytest = "~=7.0"
        """))

        result = self.svc.detect(self.repo)

        db_types = {d.database_type for d in result.databases}
        self.assertIn(DatabaseType.POSTGRESQL, db_types)
        self.assertIn(DatabaseType.REDIS, db_types)

    def test_generate_setup_commands_idempotent(self) -> None:
        """generate_setup_commands can be called independently with a result object."""
        _create_file(self.repo, "alembic.ini", "[alembic]")
        _create_file(self.repo, "alembic/env.py", "")

        result = self.svc.detect(self.repo)
        commands = self.svc.generate_setup_commands(result)

        self.assertEqual(commands, result.setup_commands)

    def test_di_factory_resolves(self) -> None:
        """DI factory function creates SchemaDetectionService correctly."""
        from automation.core import get_schema_detector_service
        svc = get_schema_detector_service()
        self.assertIsInstance(svc, SchemaDetectionService)


class TestDockerComposeParser(unittest.TestCase):
    """Focused tests for the YAML regex-based docker-compose parser."""

    def setUp(self) -> None:
        self.svc = SchemaDetectionService()

    def test_environment_list_format(self) -> None:
        """Parses environment variables in list format (- KEY=VALUE)."""
        content = textwrap.dedent("""\
            services:
              postgres:
                image: postgres:16
                environment:
                  - POSTGRES_DB=mydb
                  - POSTGRES_USER=admin
        """)
        services = self.svc._parse_compose_services(content)

        self.assertIn("postgres", services)
        self.assertEqual(services["postgres"]["environment"]["POSTGRES_DB"], "mydb")

    def test_environment_mapping_format(self) -> None:
        """Parses environment variables in mapping format (KEY: value)."""
        content = textwrap.dedent("""\
            services:
              redis:
                image: redis:7
                environment:
                  REDIS_PASSWORD: secret123
        """)
        services = self.svc._parse_compose_services(content)

        self.assertEqual(services["redis"]["environment"]["REDIS_PASSWORD"], "secret123")

    def test_services_without_image_skipped(self) -> None:
        """Services with build: instead of image: produce an empty image field."""
        content = textwrap.dedent("""\
            services:
              app:
                build: .
                ports:
                  - "3000:3000"
              postgres:
                image: postgres:16
        """)
        services = self.svc._parse_compose_services(content)

        # Both services parsed but app has no image
        self.assertEqual(services["app"]["image"], "")
        self.assertEqual(services["postgres"]["image"], "postgres:16")


if __name__ == "__main__":
    unittest.main()
