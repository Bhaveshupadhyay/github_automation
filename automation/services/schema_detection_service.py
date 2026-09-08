"""Concrete schema auto-detection service with tiered resolution strategy.

Scans a target repository's file system to detect migration frameworks, ORM models,
committed schema files, Docker Compose services, and database dependencies.
All detection is pure file I/O — no network calls, no subprocess execution.

Detection Rules Architecture:
    Rules are declared as data structures (dicts/lists), not hard-coded if-else chains.
    This makes the system extensible: adding a new framework means appending one dict.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from automation.domain.schema_detection import (
    DatabaseType,
    DetectedDatabase,
    DetectedMigration,
    DetectedORM,
    DetectedSchemaFile,
    DockerServiceDefinition,
    MigrationFramework,
    ORMFramework,
    SchemaDetectionResult,
    SchemaSourceTier,
)
from automation.interfaces.schema_detector_interface import ISchemaDetectorService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Directories to always skip during recursive scanning
# ---------------------------------------------------------------------------
EXCLUDED_DIRS: Set[str] = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".next",
    ".nuxt", "target", "vendor", ".bundle", ".cargo",
}

# ---------------------------------------------------------------------------
# Tier 1: Migration Framework Detection Rules
# ---------------------------------------------------------------------------
@dataclass
class _MigrationRule:
    """Declarative rule for detecting a migration framework."""
    framework: MigrationFramework
    file_markers: List[str]       # relative paths to check with Path.exists()
    glob_markers: List[str] = field(default_factory=list)  # glob patterns (shallow)
    setup_command: str = ""
    confidence: float = 1.0


_MIGRATION_RULES: List[_MigrationRule] = [
    # --- Python ---
    _MigrationRule(
        framework=MigrationFramework.ALEMBIC,
        file_markers=["alembic.ini", "alembic/env.py", "migrations/env.py"],
        glob_markers=["alembic/versions/*.py", "migrations/versions/*.py"],
        setup_command="alembic upgrade head",
    ),
    _MigrationRule(
        framework=MigrationFramework.DJANGO,
        file_markers=["manage.py"],
        glob_markers=["*/migrations/0001_*.py", "*/migrations/__init__.py"],
        setup_command="python manage.py migrate",
    ),
    # --- JavaScript / TypeScript ---
    _MigrationRule(
        framework=MigrationFramework.PRISMA,
        file_markers=["prisma/schema.prisma"],
        glob_markers=["prisma/migrations/*/migration.sql"],
        setup_command="npx prisma migrate deploy",
    ),
    _MigrationRule(
        framework=MigrationFramework.KNEX,
        file_markers=["knexfile.js", "knexfile.ts", "knexfile.mjs"],
        glob_markers=["migrations/*.js", "migrations/*.ts"],
        setup_command="npx knex migrate:latest",
    ),
    _MigrationRule(
        framework=MigrationFramework.SEQUELIZE,
        file_markers=[".sequelizerc"],
        glob_markers=["migrations/*.js", "migrations/*.ts", "db/migrations/*.js"],
        setup_command="npx sequelize-cli db:migrate",
    ),
    _MigrationRule(
        framework=MigrationFramework.TYPEORM,
        file_markers=["ormconfig.json", "ormconfig.ts", "ormconfig.js"],
        glob_markers=["migrations/*.ts", "src/migrations/*.ts"],
        setup_command="npx typeorm migration:run -d ./data-source.ts",
    ),
    # --- Ruby ---
    _MigrationRule(
        framework=MigrationFramework.RAILS,
        file_markers=["Rakefile", "config/database.yml"],
        glob_markers=["db/migrate/*.rb"],
        setup_command="bundle exec rails db:migrate",
    ),
    # --- Go ---
    _MigrationRule(
        framework=MigrationFramework.GOOSE,
        file_markers=[],
        glob_markers=["migrations/*.sql", "db/migrations/*.sql"],
        setup_command="goose up",
        confidence=0.7,  # lower confidence — generic .sql in migrations/ is ambiguous
    ),
    _MigrationRule(
        framework=MigrationFramework.DBMATE,
        file_markers=[".dbmaterc", "db/.dbmaterc"],
        glob_markers=["db/migrations/*.sql"],
        setup_command="dbmate up",
    ),
    # --- Java / JVM ---
    _MigrationRule(
        framework=MigrationFramework.FLYWAY,
        file_markers=["flyway.conf", "flyway.toml"],
        glob_markers=[
            "sql/V*.sql", "src/main/resources/db/migration/V*.sql",
            "db/migration/V*.sql",
        ],
        setup_command="flyway migrate",
    ),
    _MigrationRule(
        framework=MigrationFramework.LIQUIBASE,
        file_markers=["liquibase.properties"],
        glob_markers=[
            "changelog.xml", "changelog.yaml", "changelog.yml",
            "db/changelog/*.xml", "db/changelog/*.yaml",
        ],
        setup_command="liquibase update",
    ),
    # --- Rust ---
    _MigrationRule(
        framework=MigrationFramework.DIESEL,
        file_markers=["diesel.toml"],
        glob_markers=["migrations/*/up.sql", "migrations/*/down.sql"],
        setup_command="diesel migration run",
    ),
]

# ---------------------------------------------------------------------------
# Tier 2: ORM Framework Detection Rules
# ---------------------------------------------------------------------------
@dataclass
class _ORMRule:
    """Declarative rule for detecting an ORM framework from source patterns."""
    framework: ORMFramework
    file_extensions: List[str]         # file types to scan
    content_patterns: List[str]        # regex patterns to match in file content
    setup_command: str = ""
    confidence: float = 0.8


_ORM_RULES: List[_ORMRule] = [
    _ORMRule(
        framework=ORMFramework.SQLALCHEMY,
        file_extensions=[".py"],
        content_patterns=[
            r"declarative_base\s*\(",
            r"class\s+\w+\s*\(\s*DeclarativeBase\s*\)",
            r"from\s+sqlalchemy\.orm\s+import.*declarative_base",
            r"from\s+sqlalchemy\.orm\s+import.*DeclarativeBase",
            r"mapped_column\s*\(",
        ],
        setup_command="python -c \"from app.db import Base, engine; Base.metadata.create_all(engine)\"",
    ),
    _ORMRule(
        framework=ORMFramework.DJANGO_ORM,
        file_extensions=[".py"],
        content_patterns=[
            r"from\s+django\.db\s+import\s+models",
            r"class\s+\w+\s*\(\s*models\.Model\s*\)",
        ],
        setup_command="python manage.py migrate",
    ),
    _ORMRule(
        framework=ORMFramework.PRISMA_ORM,
        file_extensions=[".prisma"],
        content_patterns=[
            r"model\s+\w+\s*\{",
            r"datasource\s+\w+\s*\{",
        ],
        setup_command="npx prisma db push",
    ),
    _ORMRule(
        framework=ORMFramework.TYPEORM_ORM,
        file_extensions=[".ts", ".js"],
        content_patterns=[
            r"@Entity\s*\(",
            r"@Column\s*\(",
            r"from\s+[\"']typeorm[\"']",
        ],
        setup_command="npx typeorm schema:sync",
    ),
    _ORMRule(
        framework=ORMFramework.SEQUELIZE_ORM,
        file_extensions=[".js", ".ts"],
        content_patterns=[
            r"sequelize\.define\s*\(",
            r"Model\.init\s*\(",
            r"from\s+[\"']sequelize[\"']",
        ],
        setup_command="npx sequelize-cli db:migrate",
    ),
]

# ---------------------------------------------------------------------------
# Tier 3: Schema File Glob Patterns
# ---------------------------------------------------------------------------
_SCHEMA_FILE_GLOBS: List[str] = [
    "schema.sql", "seed.sql", "init.sql", "setup.sql", "create.sql",
    "db/schema.sql", "db/seed.sql", "db/init.sql", "db/setup.sql",
    "database/schema.sql", "database/seed.sql", "database/init.sql",
    "sql/schema.sql", "sql/init.sql", "sql/setup.sql",
    "scripts/schema.sql", "scripts/seed.sql", "scripts/init.sql",
    "docker-entrypoint-initdb.d/*.sql",
]

# ---------------------------------------------------------------------------
# Database Dependency Detection Rules
# ---------------------------------------------------------------------------
@dataclass
class _DatabaseDepRule:
    """Maps package names to database types."""
    database_type: DatabaseType
    python_packages: List[str] = field(default_factory=list)
    node_packages: List[str] = field(default_factory=list)
    ruby_gems: List[str] = field(default_factory=list)
    go_modules: List[str] = field(default_factory=list)
    container_image: str = ""
    is_schemaless: bool = False


_DATABASE_DEP_RULES: List[_DatabaseDepRule] = [
    _DatabaseDepRule(
        database_type=DatabaseType.POSTGRESQL,
        python_packages=["psycopg2", "psycopg2-binary", "psycopg", "asyncpg", "aiopg"],
        node_packages=["pg", "pg-promise", "@prisma/client"],
        ruby_gems=["pg"],
        go_modules=["github.com/lib/pq", "github.com/jackc/pgx"],
        container_image="postgres:16",
    ),
    _DatabaseDepRule(
        database_type=DatabaseType.MYSQL,
        python_packages=["pymysql", "mysql-connector-python", "aiomysql", "mysqlclient"],
        node_packages=["mysql", "mysql2"],
        ruby_gems=["mysql2"],
        go_modules=["github.com/go-sql-driver/mysql"],
        container_image="mysql:8",
    ),
    _DatabaseDepRule(
        database_type=DatabaseType.MONGODB,
        python_packages=["pymongo", "motor", "mongoengine", "beanie"],
        node_packages=["mongodb", "mongoose"],
        ruby_gems=["mongoid", "mongo"],
        go_modules=["go.mongodb.org/mongo-driver"],
        container_image="mongo:7",
        is_schemaless=True,
    ),
    _DatabaseDepRule(
        database_type=DatabaseType.REDIS,
        python_packages=["redis", "aioredis", "redis-py-cluster"],
        node_packages=["redis", "ioredis"],
        ruby_gems=["redis"],
        go_modules=["github.com/redis/go-redis", "github.com/go-redis/redis"],
        container_image="redis:7",
        is_schemaless=True,
    ),
    _DatabaseDepRule(
        database_type=DatabaseType.SQLITE,
        python_packages=["aiosqlite", "sqlite3"],
        node_packages=["better-sqlite3", "sqlite3"],
        ruby_gems=["sqlite3"],
        go_modules=["github.com/mattn/go-sqlite3"],
        container_image="",  # no container needed — file-based
        is_schemaless=False,
    ),
    _DatabaseDepRule(
        database_type=DatabaseType.TYPESENSE,
        python_packages=["typesense"],
        node_packages=["typesense"],
        container_image="typesense/typesense:27.1",
        is_schemaless=True,  # schema created via API calls in application code
    ),
    _DatabaseDepRule(
        database_type=DatabaseType.ELASTICSEARCH,
        python_packages=["elasticsearch", "opensearch-py"],
        node_packages=["@elastic/elasticsearch", "opensearch"],
        container_image="elasticsearch:8.15.0",
        is_schemaless=True,
    ),
    _DatabaseDepRule(
        database_type=DatabaseType.COSMOS_DB,
        python_packages=["azure-cosmos"],
        node_packages=["@azure/cosmos"],
        container_image="",  # no portable emulator for CI
        is_schemaless=True,
    ),
]

# ---------------------------------------------------------------------------
# Docker image → DatabaseType mapping (for docker-compose parsing)
# ---------------------------------------------------------------------------
_IMAGE_TO_DB_TYPE: Dict[str, DatabaseType] = {
    "postgres": DatabaseType.POSTGRESQL,
    "mysql": DatabaseType.MYSQL,
    "mariadb": DatabaseType.MYSQL,
    "mongo": DatabaseType.MONGODB,
    "redis": DatabaseType.REDIS,
    "typesense/typesense": DatabaseType.TYPESENSE,
    "elasticsearch": DatabaseType.ELASTICSEARCH,
    "opensearchproject/opensearch": DatabaseType.ELASTICSEARCH,
}

# ---------------------------------------------------------------------------
# Docker compose file names to look for
# ---------------------------------------------------------------------------
_COMPOSE_FILES: List[str] = [
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "docker-compose.dev.yml",
    "docker-compose.dev.yaml",
    "docker-compose.test.yml",
    "docker-compose.test.yaml",
]

# Maximum number of source files to scan for ORM patterns (performance guard)
_MAX_ORM_SCAN_FILES: int = 500


class SchemaDetectionService(ISchemaDetectorService):
    """Concrete implementation that scans a repo and produces a SchemaDetectionResult.

    Pure file-system scanning — no network calls, no subprocess execution.
    Uses data-driven rule lists for extensibility.
    """

    def detect(self, repo_dir: Path) -> SchemaDetectionResult:
        """Scans the repository and returns a complete detection result."""
        repo_dir = repo_dir.resolve()
        if not repo_dir.is_dir():
            raise FileNotFoundError(f"Repository directory does not exist: {repo_dir}")

        logger.info("Schema detection started for: %s", repo_dir)

        # Run all detection passes
        migrations = self._detect_migration_frameworks(repo_dir)
        orm_models = self._detect_orm_frameworks(repo_dir)
        schema_files = self._detect_schema_files(repo_dir)
        databases = self._detect_databases_from_dependencies(repo_dir)
        docker_services = self._detect_docker_services(repo_dir)

        # Enrich databases from docker services
        databases = self._merge_docker_databases(databases, docker_services)

        # Resolve the best available tier
        resolved_tier = self._resolve_tier(migrations, orm_models, schema_files, docker_services)

        # Build setup commands based on tier
        result = SchemaDetectionResult(
            repo_dir=str(repo_dir),
            resolved_tier=resolved_tier,
            migrations=migrations,
            orm_models=orm_models,
            schema_files=schema_files,
            databases=databases,
            docker_services=docker_services,
        )
        result.setup_commands = self.generate_setup_commands(result)
        result.warnings = self._build_warnings(result)

        logger.info(
            "Schema detection complete: tier=%s, migrations=%d, orms=%d, schemas=%d, dbs=%d",
            resolved_tier.value, len(migrations), len(orm_models),
            len(schema_files), len(databases),
        )
        return result

    def generate_setup_commands(self, result: SchemaDetectionResult) -> List[str]:
        """Generates ordered setup commands based on the resolved tier."""
        commands: List[str] = []

        if result.resolved_tier == SchemaSourceTier.MIGRATIONS and result.migrations:
            # Pick the highest-confidence migration framework
            best = max(result.migrations, key=lambda m: m.confidence)
            commands.append(f"# Tier 1: Run {best.framework.value} migrations")
            commands.append(best.setup_command)

        elif result.resolved_tier == SchemaSourceTier.ORM_MODELS and result.orm_models:
            best = max(result.orm_models, key=lambda o: o.confidence)
            commands.append(f"# Tier 2: Sync schema from {best.framework.value} models")
            commands.append(best.setup_command)

        elif result.resolved_tier == SchemaSourceTier.SCHEMA_FILES:
            for sf in result.schema_files:
                db_hint = sf.database_type.value if sf.database_type else "unknown"
                commands.append(f"# Tier 3: Apply schema file ({db_hint})")
                if sf.database_type == DatabaseType.POSTGRESQL:
                    commands.append(f"psql -h $PGHOST -U $PGUSER -d $PGDATABASE -f {sf.path}")
                elif sf.database_type == DatabaseType.MYSQL:
                    commands.append(f"mysql -h $MYSQL_HOST -u $MYSQL_USER $MYSQL_DATABASE < {sf.path}")
                else:
                    commands.append(f"# Apply {sf.path} using appropriate database client")

        elif result.resolved_tier == SchemaSourceTier.DOCKER_COMPOSE:
            commands.append("# Tier 4: Start services from docker-compose")
            compose_file = self._find_first_compose_file(Path(result.repo_dir))
            if compose_file:
                commands.append(f"docker compose -f {compose_file} up -d")

        else:
            commands.append("# Tier 5: No schema source detected")
            commands.append("# Run: pg_dump --schema-only -h <dev-host> -U <user> -d <db> > db/schema.sql")
            commands.append("# Then commit db/schema.sql to the repository")

        return commands

    # -----------------------------------------------------------------------
    # Tier 1: Migration Framework Detection
    # -----------------------------------------------------------------------
    def _detect_migration_frameworks(self, repo_dir: Path) -> List[DetectedMigration]:
        """Scans for migration framework marker files and directories."""
        detected: List[DetectedMigration] = []

        for rule in _MIGRATION_RULES:
            found_markers: List[str] = []

            # Check explicit file markers
            for marker in rule.file_markers:
                marker_path = repo_dir / marker
                if marker_path.exists():
                    found_markers.append(marker)

            # Check glob markers (limited depth)
            for pattern in rule.glob_markers:
                matches = list(repo_dir.glob(pattern))
                if matches:
                    # Store just the first few as evidence
                    for m in matches[:3]:
                        rel = str(m.relative_to(repo_dir))
                        if rel not in found_markers:
                            found_markers.append(rel)

            if found_markers:
                # Django needs both manage.py AND migration files
                if rule.framework == MigrationFramework.DJANGO:
                    has_manage = any("manage.py" in m for m in found_markers)
                    has_migrations = any("migrations/" in m for m in found_markers)
                    if not (has_manage and has_migrations):
                        continue

                # Goose has ambiguous markers — only if no other framework claims them
                if rule.framework == MigrationFramework.GOOSE:
                    # Skip if another framework already detected these files
                    already_claimed = any(
                        d.framework != MigrationFramework.GOOSE for d in detected
                    )
                    if already_claimed:
                        continue

                detected.append(DetectedMigration(
                    framework=rule.framework,
                    marker_files=found_markers,
                    setup_command=rule.setup_command,
                    confidence=rule.confidence,
                ))
                logger.debug(
                    "Detected migration framework: %s (markers: %s)",
                    rule.framework.value, found_markers,
                )

        return detected

    # -----------------------------------------------------------------------
    # Tier 2: ORM Framework Detection
    # -----------------------------------------------------------------------
    def _detect_orm_frameworks(self, repo_dir: Path) -> List[DetectedORM]:
        """Scans source files for ORM model definition patterns."""
        detected: List[DetectedORM] = []
        # Collect source files, respecting exclusion dirs and scan limit
        source_files = self._collect_source_files(repo_dir)

        for rule in _ORM_RULES:
            matched_files: List[str] = []
            compiled = [re.compile(p) for p in rule.content_patterns]

            for fpath in source_files:
                if fpath.suffix not in rule.file_extensions:
                    continue
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    if any(pat.search(content) for pat in compiled):
                        rel = str(fpath.relative_to(repo_dir))
                        matched_files.append(rel)
                        if len(matched_files) >= 5:  # enough evidence
                            break
                except (OSError, UnicodeDecodeError):
                    continue

            if matched_files:
                detected.append(DetectedORM(
                    framework=rule.framework,
                    marker_files=matched_files,
                    setup_command=rule.setup_command,
                    confidence=rule.confidence,
                ))
                logger.debug(
                    "Detected ORM framework: %s (files: %s)",
                    rule.framework.value, matched_files,
                )

        return detected

    # -----------------------------------------------------------------------
    # Tier 3: Committed Schema File Detection
    # -----------------------------------------------------------------------
    def _detect_schema_files(self, repo_dir: Path) -> List[DetectedSchemaFile]:
        """Finds committed SQL schema or seed files using known glob patterns."""
        detected: List[DetectedSchemaFile] = []
        seen_paths: Set[str] = set()

        for pattern in _SCHEMA_FILE_GLOBS:
            for match in repo_dir.glob(pattern):
                if not match.is_file():
                    continue
                rel = str(match.relative_to(repo_dir))
                if rel in seen_paths:
                    continue
                seen_paths.add(rel)

                # Try to infer database type from content
                db_type = self._infer_db_type_from_sql(match)

                detected.append(DetectedSchemaFile(
                    path=rel,
                    size_bytes=match.stat().st_size,
                    database_type=db_type,
                ))

        return detected

    # -----------------------------------------------------------------------
    # Database Dependency Detection
    # -----------------------------------------------------------------------
    def _detect_databases_from_dependencies(self, repo_dir: Path) -> List[DetectedDatabase]:
        """Parses dependency files to identify which databases the project uses."""
        detected: List[DetectedDatabase] = []
        seen_types: Set[DatabaseType] = set()

        # Collect all dependency names from various package managers
        deps_by_source = self._parse_all_dependencies(repo_dir)

        for rule in _DATABASE_DEP_RULES:
            for source, dep_names in deps_by_source.items():
                # Choose the right package list based on source type
                packages_to_check: List[str] = []
                if source.endswith(".txt") or source in ("pyproject.toml", "Pipfile", "setup.py", "setup.cfg"):
                    packages_to_check = rule.python_packages
                elif source == "package.json":
                    packages_to_check = rule.node_packages
                elif source == "Gemfile":
                    packages_to_check = rule.ruby_gems
                elif source == "go.mod":
                    packages_to_check = rule.go_modules

                matched_pkg = self._find_matching_package(dep_names, packages_to_check)
                if matched_pkg and rule.database_type not in seen_types:
                    seen_types.add(rule.database_type)
                    detected.append(DetectedDatabase(
                        database_type=rule.database_type,
                        detection_source=f"{source} ({matched_pkg})",
                        container_image=rule.container_image or None,
                        is_schemaless=rule.is_schemaless,
                    ))
                    logger.debug(
                        "Detected database %s from %s (%s)",
                        rule.database_type.value, source, matched_pkg,
                    )

        return detected

    # -----------------------------------------------------------------------
    # Tier 4: Docker Compose Service Detection
    # -----------------------------------------------------------------------
    def _detect_docker_services(self, repo_dir: Path) -> List[DockerServiceDefinition]:
        """Parses docker-compose files to find database service definitions.

        Uses regex-based extraction to avoid requiring PyYAML as a dependency.
        """
        detected: List[DockerServiceDefinition] = []

        compose_path = self._find_first_compose_file(repo_dir)
        if not compose_path:
            return detected

        try:
            content = (repo_dir / compose_path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return detected

        # Parse services using regex — handles standard docker-compose format
        services = self._parse_compose_services(content)
        for svc_name, svc_data in services.items():
            image = svc_data.get("image", "")
            if not image:
                continue

            # Map image to database type
            db_type = self._map_image_to_db_type(image)

            ports = svc_data.get("ports", [])
            env = svc_data.get("environment", {})

            detected.append(DockerServiceDefinition(
                service_name=svc_name,
                image=image,
                ports=ports,
                environment=env,
                database_type=db_type,
            ))

        return detected

    # -----------------------------------------------------------------------
    # Resolution & Warning Logic
    # -----------------------------------------------------------------------
    def _resolve_tier(
        self,
        migrations: List[DetectedMigration],
        orm_models: List[DetectedORM],
        schema_files: List[DetectedSchemaFile],
        docker_services: List[DockerServiceDefinition],
    ) -> SchemaSourceTier:
        """Determines the best available schema source tier."""
        if migrations:
            return SchemaSourceTier.MIGRATIONS
        if orm_models:
            return SchemaSourceTier.ORM_MODELS
        if schema_files:
            return SchemaSourceTier.SCHEMA_FILES
        if any(ds.database_type is not None for ds in docker_services):
            return SchemaSourceTier.DOCKER_COMPOSE
        return SchemaSourceTier.NONE_FOUND

    def _build_warnings(self, result: SchemaDetectionResult) -> List[str]:
        """Generates actionable warnings for edge cases."""
        warnings: List[str] = []

        # No schema source at all
        if result.resolved_tier == SchemaSourceTier.NONE_FOUND:
            if result.databases:
                db_names = ", ".join(d.database_type.value for d in result.databases)
                warnings.append(
                    f"Databases detected ({db_names}) but no schema source found. "
                    "Run 'pg_dump --schema-only > db/schema.sql' and commit it, "
                    "or add a migration framework (Alembic, Prisma, etc.)."
                )
            else:
                warnings.append(
                    "No databases or schema sources detected. "
                    "If this project uses a database, ensure dependencies are declared "
                    "in requirements.txt / package.json."
                )

        # ORM-only (no migrations) — schema may be incomplete
        if result.resolved_tier == SchemaSourceTier.ORM_MODELS and not result.migrations:
            orm_names = ", ".join(o.framework.value for o in result.orm_models)
            warnings.append(
                f"Schema will be generated from ORM models ({orm_names}). "
                "This may miss database triggers, views, indexes, and stored procedures. "
                "Consider adding a migration framework for complete schema fidelity."
            )

        # Schema file but also has databases without files
        if result.resolved_tier == SchemaSourceTier.SCHEMA_FILES:
            schema_dbs = {sf.database_type for sf in result.schema_files if sf.database_type}
            all_dbs = {d.database_type for d in result.databases if not d.is_schemaless}
            uncovered = all_dbs - schema_dbs
            if uncovered:
                missing = ", ".join(db.value for db in uncovered)
                warnings.append(
                    f"Schema files found but not covering all databases. "
                    f"Missing schema files for: {missing}."
                )

        # Schemaless databases that need containers
        schemaless_dbs = [d for d in result.databases if d.is_schemaless]
        for db in schemaless_dbs:
            if db.database_type == DatabaseType.COSMOS_DB:
                warnings.append(
                    "Azure Cosmos DB detected but has no portable local emulator for CI. "
                    "Consider mocking the Cosmos client in tests, "
                    "or using the Azure Cosmos Emulator (Linux preview, ~2GB image)."
                )

        # Multiple migration frameworks detected — potential conflict
        if len(result.migrations) > 1:
            fw_names = ", ".join(m.framework.value for m in result.migrations)
            warnings.append(
                f"Multiple migration frameworks detected ({fw_names}). "
                "The highest-confidence framework will be used for schema setup."
            )

        # Docker services exist but no compose for some detected databases
        docker_db_types = {ds.database_type for ds in result.docker_services if ds.database_type}
        dep_db_types = {d.database_type for d in result.databases if d.container_image}
        uncovered_docker = dep_db_types - docker_db_types
        if uncovered_docker and result.docker_services:
            missing = ", ".join(db.value for db in uncovered_docker)
            warnings.append(
                f"Docker Compose exists but is missing services for: {missing}. "
                "Consider adding these to docker-compose for complete local dev setup."
            )

        return warnings

    # -----------------------------------------------------------------------
    # Helper: Merge docker-detected databases into main list
    # -----------------------------------------------------------------------
    def _merge_docker_databases(
        self,
        databases: List[DetectedDatabase],
        docker_services: List[DockerServiceDefinition],
    ) -> List[DetectedDatabase]:
        """Adds databases found in docker-compose that weren't in dependency files."""
        existing_types = {d.database_type for d in databases}
        merged = list(databases)

        for ds in docker_services:
            if ds.database_type and ds.database_type not in existing_types:
                existing_types.add(ds.database_type)
                rule = next(
                    (r for r in _DATABASE_DEP_RULES if r.database_type == ds.database_type),
                    None,
                )
                merged.append(DetectedDatabase(
                    database_type=ds.database_type,
                    detection_source=f"docker-compose ({ds.service_name})",
                    container_image=ds.image,
                    is_schemaless=rule.is_schemaless if rule else False,
                ))

        return merged

    # -----------------------------------------------------------------------
    # Helper: Collect source files for ORM scanning (with exclusions)
    # -----------------------------------------------------------------------
    def _collect_source_files(self, repo_dir: Path) -> List[Path]:
        """Recursively collects scannable source files, skipping excluded dirs."""
        source_files: List[Path] = []
        scannable_extensions = {".py", ".js", ".ts", ".prisma", ".rb", ".go", ".rs", ".java"}

        def _walk(directory: Path, depth: int = 0) -> None:
            if depth > 8:  # max recursion depth guard
                return
            try:
                entries = sorted(directory.iterdir())
            except PermissionError:
                return

            for entry in entries:
                if entry.name in EXCLUDED_DIRS:
                    continue
                if entry.is_dir():
                    _walk(entry, depth + 1)
                elif entry.is_file() and entry.suffix in scannable_extensions:
                    source_files.append(entry)
                    if len(source_files) >= _MAX_ORM_SCAN_FILES:
                        return

        _walk(repo_dir)
        return source_files

    # -----------------------------------------------------------------------
    # Helper: Parse dependency files
    # -----------------------------------------------------------------------
    def _parse_all_dependencies(self, repo_dir: Path) -> Dict[str, Set[str]]:
        """Reads known dependency manifest files and extracts package names.

        Returns a dict mapping source filename to a set of lowercased package names.
        """
        deps: Dict[str, Set[str]] = {}

        # --- Python: requirements.txt ---
        for req_file in ["requirements.txt", "requirements/base.txt", "requirements/dev.txt",
                         "requirements/production.txt", "requirements-dev.txt"]:
            path = repo_dir / req_file
            if path.is_file():
                deps[req_file] = self._parse_requirements_txt(path)

        # --- Python: pyproject.toml ---
        pyproject = repo_dir / "pyproject.toml"
        if pyproject.is_file():
            deps["pyproject.toml"] = self._parse_pyproject_toml(pyproject)

        # --- Python: Pipfile ---
        pipfile = repo_dir / "Pipfile"
        if pipfile.is_file():
            deps["Pipfile"] = self._parse_pipfile(pipfile)

        # --- Node.js: package.json ---
        pkg_json = repo_dir / "package.json"
        if pkg_json.is_file():
            deps["package.json"] = self._parse_package_json(pkg_json)

        # --- Ruby: Gemfile ---
        gemfile = repo_dir / "Gemfile"
        if gemfile.is_file():
            deps["Gemfile"] = self._parse_gemfile(gemfile)

        # --- Go: go.mod ---
        gomod = repo_dir / "go.mod"
        if gomod.is_file():
            deps["go.mod"] = self._parse_gomod(gomod)

        return deps

    def _parse_requirements_txt(self, path: Path) -> Set[str]:
        """Extracts package names from a pip requirements file."""
        packages: Set[str] = set()
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                # Extract package name before version specifiers
                match = re.match(r"^([a-zA-Z0-9_-]+)", line)
                if match:
                    packages.add(match.group(1).lower())
        except OSError:
            pass
        return packages

    def _parse_pyproject_toml(self, path: Path) -> Set[str]:
        """Extracts dependency names from pyproject.toml (basic line-by-line parsing).

        Handles both array-style dependencies:
            "psycopg2-binary~=2.9.9",
            "psycopg[binary,pool]~=3.2.9",
        And Poetry key-value format:
            redis = "^4.0"
        """
        packages: Set[str] = set()
        # Regex to extract package name from a quoted dependency string
        # Matches: "package-name", "package[extras]>=1.0", 'package~=2.0'
        _dep_pattern = re.compile(r'^\s*["\']([a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?)')
        # Regex for Poetry-style: package-name = "^4.0"
        _poetry_pattern = re.compile(r'^([a-zA-Z][a-zA-Z0-9_-]*)\s*=')
        # TOML keys to ignore (not package names)
        _ignore_keys = {
            "name", "version", "description", "readme", "python", "requires-python",
            "license", "authors", "classifiers", "build-system", "tool", "project",
            "homepage", "repository", "documentation", "keywords", "packages",
            "include", "exclude", "scripts", "plugins", "extras", "optional-dependencies",
            "urls", "entry-points", "gui-scripts", "source", "dev-dependencies",
            "line-length", "target-version", "select", "ignore", "fixable", "unfixable",
            "ignore-paths", "formatter-cmds",
        }
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("["):
                    continue
                # Try quoted dependency format first
                m = _dep_pattern.match(stripped)
                if m:
                    packages.add(m.group(1).lower())
                    continue
                # Try Poetry key-value format
                m = _poetry_pattern.match(stripped)
                if m:
                    name = m.group(1).lower()
                    if name not in _ignore_keys and len(name) > 1:
                        packages.add(name)
        except OSError:
            pass
        return packages

    def _parse_pipfile(self, path: Path) -> Set[str]:
        """Extracts package names from Pipfile."""
        packages: Set[str] = set()
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            in_packages = False
            for line in content.splitlines():
                stripped = line.strip()
                if stripped in ("[packages]", "[dev-packages]"):
                    in_packages = True
                    continue
                if stripped.startswith("[") and in_packages:
                    in_packages = False
                    continue
                if in_packages and "=" in stripped:
                    name = stripped.split("=")[0].strip().strip('"').strip("'")
                    if name:
                        packages.add(name.lower())
        except OSError:
            pass
        return packages

    def _parse_package_json(self, path: Path) -> Set[str]:
        """Extracts dependency names from package.json."""
        packages: Set[str] = set()
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                if section in data and isinstance(data[section], dict):
                    packages.update(k.lower() for k in data[section].keys())
        except (OSError, json.JSONDecodeError):
            pass
        return packages

    def _parse_gemfile(self, path: Path) -> Set[str]:
        """Extracts gem names from a Ruby Gemfile."""
        packages: Set[str] = set()
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r"""gem\s+['"]([a-zA-Z0-9_-]+)['"]""", content):
                packages.add(match.group(1).lower())
        except OSError:
            pass
        return packages

    def _parse_gomod(self, path: Path) -> Set[str]:
        """Extracts module paths from go.mod."""
        modules: Set[str] = set()
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r"^\s+([\w./-]+)\s+v", content, re.MULTILINE):
                modules.add(match.group(1).lower())
        except OSError:
            pass
        return modules

    # -----------------------------------------------------------------------
    # Helper: Find matching package from a dependency set
    # -----------------------------------------------------------------------
    @staticmethod
    def _find_matching_package(dep_names: Set[str], packages_to_check: List[str]) -> Optional[str]:
        """Returns the first matching package name, or None.

        Uses exact matching for standard package names, and prefix matching
        for Go module paths (which contain slashes and version suffixes like /v9).
        """
        for pkg in packages_to_check:
            pkg_lower = pkg.lower()
            # Exact match (standard packages)
            if pkg_lower in dep_names:
                return pkg
            # Prefix match for Go modules (github.com/redis/go-redis matches go-redis/v9)
            if "/" in pkg_lower:
                for dep in dep_names:
                    if dep.startswith(pkg_lower):
                        return pkg
        return None

    # -----------------------------------------------------------------------
    # Helper: Infer database type from SQL file content
    # -----------------------------------------------------------------------
    @staticmethod
    def _infer_db_type_from_sql(path: Path) -> Optional[DatabaseType]:
        """Reads a SQL file and infers which database engine it targets."""
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")[:4096]  # first 4KB
            content_upper = content.upper()

            # PostgreSQL-specific syntax
            pg_signals = ["SERIAL", "BIGSERIAL", "UUID_GENERATE", "CREATE EXTENSION",
                          "RETURNING", "ON CONFLICT", "JSONB", "TEXT[]"]
            if any(sig in content_upper for sig in pg_signals):
                return DatabaseType.POSTGRESQL

            # MySQL-specific syntax
            mysql_signals = ["ENGINE=INNODB", "AUTO_INCREMENT", "UNSIGNED",
                             "COLLATE UTF8", "ENGINE=MYISAM"]
            if any(sig in content_upper for sig in mysql_signals):
                return DatabaseType.MYSQL

            # Generic SQL — default to PostgreSQL (most common in modern stacks)
            if "CREATE TABLE" in content_upper:
                return DatabaseType.POSTGRESQL

        except OSError:
            pass
        return None

    # -----------------------------------------------------------------------
    # Helper: Docker Compose parsing (regex-based, no PyYAML required)
    # -----------------------------------------------------------------------
    def _find_first_compose_file(self, repo_dir: Path) -> Optional[str]:
        """Finds the first existing docker-compose file in the repo."""
        for name in _COMPOSE_FILES:
            if (repo_dir / name).is_file():
                return name
        return None

    def _parse_compose_services(self, content: str) -> Dict[str, Dict]:
        """Extracts service definitions from docker-compose YAML using regex.

        This is intentionally simple — we only need service names, images, and ports.
        For complex compose files, this covers the 90% case without requiring PyYAML.
        Handles arbitrary valid indentation levels under services:.
        """
        services: Dict[str, Dict] = {}
        lines = content.splitlines()
        in_services = False
        current_service: Optional[str] = None
        current_key: Optional[str] = None
        service_indent: Optional[int] = None
        prop_indent: Optional[int] = None

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Detect the `services:` top-level key
            if re.match(r"^services\s*:", line):
                in_services = True
                service_indent = None
                prop_indent = None
                continue

            if not in_services:
                continue

            # Detect a top-level key other than services (end of services block)
            if re.match(r"^[a-zA-Z0-9_-]+\s*:", line) and not line.startswith(" "):
                in_services = False
                current_service = None
                continue

            # Calculate indentation
            leading_spaces = len(line) - len(line.lstrip())

            # Detect service name under services:
            svc_match = re.match(r"^(\s+)([a-zA-Z0-9_-]+)\s*:", line)
            if svc_match:
                spaces = len(svc_match.group(1))
                if service_indent is None:
                    service_indent = spaces
                if spaces == service_indent:
                    current_service = svc_match.group(2)
                    services[current_service] = {"image": "", "ports": [], "environment": {}}
                    current_key = None
                    prop_indent = None
                    continue

            if current_service is None or service_indent is None:
                continue

            # Service-level properties (indented deeper than service name)
            if leading_spaces > service_indent:
                if prop_indent is None:
                    if re.match(r"^\s+([a-zA-Z_]+)\s*:", line):
                        prop_indent = leading_spaces

                if prop_indent is not None and leading_spaces == prop_indent:
                    img_match = re.match(r"^\s+image\s*:\s*(.+)", line)
                    if img_match:
                        services[current_service]["image"] = img_match.group(1).strip().strip("'\"")
                        current_key = None
                        continue

                    # Ports list header
                    if re.match(r"^\s+ports\s*:", line):
                        current_key = "ports"
                        continue

                    # Environment header
                    if re.match(r"^\s+environment\s*:", line):
                        current_key = "environment"
                        continue

                    # Any other service-level property resets the current_key
                    current_key = None
                    continue

                # Items nested under a current_key (indented deeper than prop_indent)
                if current_key and (prop_indent is None or leading_spaces > prop_indent):
                    if current_key == "ports":
                        port_match = re.match(r'^\s+-\s*["\']?([^"\']+)["\']?', line)
                        if port_match:
                            services[current_service]["ports"].append(port_match.group(1).strip())
                        continue

                    if current_key == "environment":
                        # List-style: - KEY=VALUE
                        env_list_match = re.match(r'^\s+-\s*["\']?(\w+)=([^"\']*)["\']?', line)
                        if env_list_match:
                            services[current_service]["environment"][env_list_match.group(1)] = (
                                env_list_match.group(2).strip()
                            )
                            continue
                        # Mapping-style: KEY: value
                        env_match = re.match(r"^\s+(\w+)\s*:\s*(.+)", line)
                        if env_match:
                            services[current_service]["environment"][env_match.group(1)] = (
                                env_match.group(2).strip().strip("'\"")
                            )
                            continue

        return services

    @staticmethod
    def _map_image_to_db_type(image: str) -> Optional[DatabaseType]:
        """Maps a Docker image name to a DatabaseType."""
        image_lower = image.lower()
        for prefix, db_type in _IMAGE_TO_DB_TYPE.items():
            if image_lower.startswith(prefix):
                return db_type
        return None
