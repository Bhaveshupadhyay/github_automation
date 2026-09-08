"""Domain models for schema auto-detection and tiered database setup.

Covers migration frameworks, ORM discovery, schema file detection,
Docker Compose service parsing, and database type identification.
"""
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class MigrationFramework(str, Enum):
    """Supported migration frameworks that can be auto-detected."""
    ALEMBIC = "alembic"
    DJANGO = "django"
    PRISMA = "prisma"
    FLYWAY = "flyway"
    KNEX = "knex"
    RAILS = "rails"
    SEQUELIZE = "sequelize"
    TYPEORM = "typeorm"
    DIESEL = "diesel"
    GOOSE = "goose"
    LIQUIBASE = "liquibase"
    DBMATE = "dbmate"


class ORMFramework(str, Enum):
    """Supported ORM frameworks whose models can generate schema."""
    SQLALCHEMY = "sqlalchemy"
    DJANGO_ORM = "django_orm"
    PRISMA_ORM = "prisma"
    TYPEORM_ORM = "typeorm"
    SEQUELIZE_ORM = "sequelize"


class DatabaseType(str, Enum):
    """Database engines detectable from project dependencies."""
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    MONGODB = "mongodb"
    REDIS = "redis"
    SQLITE = "sqlite"
    TYPESENSE = "typesense"
    ELASTICSEARCH = "elasticsearch"
    COSMOS_DB = "cosmos_db"


class SchemaSourceTier(str, Enum):
    """Priority tier indicating which schema source was resolved.

    Tier 1 is best (auto-updating), Tier 5 means nothing was found.
    """
    MIGRATIONS = "tier_1_migrations"
    ORM_MODELS = "tier_2_orm_models"
    SCHEMA_FILES = "tier_3_schema_files"
    DOCKER_COMPOSE = "tier_4_docker_compose"
    NONE_FOUND = "tier_5_none_found"


class DetectedMigration(BaseModel):
    """A migration framework detected in the target repository."""
    framework: MigrationFramework = Field(..., description="Identified migration framework")
    marker_files: List[str] = Field(
        default_factory=list,
        description="Relative paths of files/dirs that triggered detection",
    )
    setup_command: str = Field(..., description="Shell command to apply migrations from scratch")
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Detection confidence (1.0 = definitive marker file found)",
    )


class DetectedORM(BaseModel):
    """An ORM framework detected in the target repository."""
    framework: ORMFramework = Field(..., description="Identified ORM framework")
    marker_files: List[str] = Field(
        default_factory=list,
        description="Files containing ORM model definitions",
    )
    setup_command: str = Field(..., description="Shell command or snippet to sync schema from models")
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Detection confidence",
    )


class DetectedSchemaFile(BaseModel):
    """A committed SQL schema or seed file found in the repository."""
    path: str = Field(..., description="Relative path from repo root")
    size_bytes: int = Field(..., description="File size in bytes")
    database_type: Optional[DatabaseType] = Field(
        None, description="Database type inferred from file content",
    )


class DetectedDatabase(BaseModel):
    """A database engine detected from project dependencies or config."""
    database_type: DatabaseType = Field(..., description="Identified database engine")
    detection_source: str = Field(
        ..., description="File or signal that triggered detection (e.g. 'requirements.txt')",
    )
    container_image: Optional[str] = Field(
        None, description="Recommended Docker image (e.g. 'postgres:16')",
    )
    is_schemaless: bool = Field(
        default=False,
        description="True for databases that don't require schema setup (Redis, MongoDB, etc.)",
    )


class DockerServiceDefinition(BaseModel):
    """A service parsed from a docker-compose file."""
    service_name: str = Field(..., description="Compose service name")
    image: str = Field(..., description="Docker image reference")
    ports: List[str] = Field(default_factory=list, description="Port mappings (e.g. '5432:5432')")
    environment: Dict[str, str] = Field(
        default_factory=dict, description="Environment variables",
    )
    database_type: Optional[DatabaseType] = Field(
        None, description="Mapped database type from known image prefixes",
    )


class SchemaDetectionResult(BaseModel):
    """Complete result of scanning a repository for schema sources and databases."""
    repo_dir: str = Field(..., description="Absolute path to the scanned repository")
    resolved_tier: SchemaSourceTier = Field(
        ..., description="Best available schema source tier",
    )
    migrations: List[DetectedMigration] = Field(
        default_factory=list, description="Tier 1: Detected migration frameworks",
    )
    orm_models: List[DetectedORM] = Field(
        default_factory=list, description="Tier 2: Detected ORM model sources",
    )
    schema_files: List[DetectedSchemaFile] = Field(
        default_factory=list, description="Tier 3: Committed schema/seed SQL files",
    )
    databases: List[DetectedDatabase] = Field(
        default_factory=list, description="All detected database engines",
    )
    docker_services: List[DockerServiceDefinition] = Field(
        default_factory=list, description="Tier 4: Services from docker-compose",
    )
    setup_commands: List[str] = Field(
        default_factory=list, description="Ordered shell commands to set up the database",
    )
    warnings: List[str] = Field(
        default_factory=list, description="Edge case warnings and recommendations",
    )
