from __future__ import annotations

from enum import Enum


class ProjectType(str, Enum):
    PROJECT = "project"
    TOOL = "tool"
    FRAMEWORK = "framework"
    PAPER_IMPL = "paper_impl"
    PRODUCT = "product"


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class ProjectSourceType(str, Enum):
    API = "api"
    RSS = "rss"
    WEB = "web"
    MANUAL = "manual"
    GITHUB = "github"
    PAPER = "paper"
    OFFICIAL_BLOG = "official_blog"
    COMMUNITY = "community"


class IntegrationDifficulty(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReuseLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProjectAction(str, Enum):
    VIEW = "view"
    SAVE = "save"
    WATCH = "watch"
    OPEN_LAB = "open_lab"
    ADD_TO_COLLECTION = "add_to_collection"
    TEST = "test"
    ANALYZE = "analyze"


class CollectionType(str, Enum):
    TOPIC = "topic"
    TOOLSET = "toolset"
    CASEBOOK = "casebook"
    WATCHPACK = "watchpack"
    UI_REFERENCE = "ui_reference"
    IMPLEMENTATION_PATH = "implementation_path"


class LabSessionStatus(str, Enum):
    ACTIVE = "active"
    SAVED = "saved"
    ADOPTED = "adopted"
    ARCHIVED = "archived"
