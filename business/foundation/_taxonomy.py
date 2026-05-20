from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - convenience
        return str(self.value)


class ScoreLevel(StrEnum):
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class ConfidenceMethod(StrEnum):
    RULE_BASED = "rule_based"
    LLM_EXTRACTED = "llm_extracted"
    EMBEDDING_SIMILARITY = "embedding_similarity"
    EXACT_MATCH = "exact_match"
    HUMAN_VERIFIED = "human_verified"
    HYBRID = "hybrid"


class SourceReliability(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    OFFICIAL = "official"
    UNKNOWN = "unknown"


class SignalType(StrEnum):
    AI_NEWS = "ai_news"
    GITHUB_PROJECT = "github_project"
    PAPER = "paper"
    COMMUNITY_DISCUSSION = "community_discussion"


class BoardType(StrEnum):
    AI_NEWS = "ai_news"
    PROJECT_RADAR = "project_radar"
    PAPER_RADAR = "paper_radar"
    COMMUNITY_PULSE = "community_pulse"
    CROSS_BOARD = "cross_board"


class SourceType(StrEnum):
    RSS = "rss"
    OFFICIAL_BLOG = "official_blog"
    GITHUB = "github"
    ARXIV = "arxiv"
    PAPER_INDEX = "paper_index"
    HACKERNEWS = "hackernews"
    REDDIT = "reddit"
    GITHUB_DISCUSSION = "github_discussion"
    MANUAL = "manual"
    HTML = "html"
    WEB_PAGE = "web_page"
    DEVTO = "devto"
    MEDIUM = "medium"
    LOBSTERS = "lobsters"
    STACKOVERFLOW = "stackoverflow"


class EntityType(StrEnum):
    COMPANY = "company"
    PRODUCT = "product"
    MODEL = "model"
    FRAMEWORK = "framework"
    LIBRARY = "library"
    GITHUB_PROJECT = "github_project"
    PAPER = "paper"
    AUTHOR = "author"
    ORGANIZATION = "organization"
    BENCHMARK = "benchmark"
    DATASET = "dataset"
    COMMUNITY = "community"
    PERSON = "person"
    UNKNOWN = "unknown"


class TechnologyCategory(StrEnum):
    AGENT = "agent"
    RAG = "rag"
    LLM_INFERENCE = "llm_inference"
    LLM_TRAINING = "llm_training"
    MULTIMODAL = "multimodal"
    AI_CODING = "ai_coding"
    EVALUATION = "evaluation"
    MEMORY = "memory"
    PLANNING = "planning"
    TOOL_USE = "tool_use"
    WORKFLOW = "workflow"
    MODEL_SERVING = "model_serving"
    FINE_TUNING = "fine_tuning"
    DATA_ENGINEERING = "data_engineering"
    SAFETY = "safety"
    ALIGNMENT = "alignment"
    BENCHMARK = "benchmark"
    UNKNOWN = "unknown"


class ClaimType(StrEnum):
    FACT = "fact"
    OPINION = "opinion"
    COMPARISON = "comparison"
    TECHNICAL_METHOD = "technical_method"
    PERFORMANCE_CLAIM = "performance_claim"
    ADOPTION_CLAIM = "adoption_claim"
    IMPLEMENTATION_CLAIM = "implementation_claim"
    COMMUNITY_FEEDBACK = "community_feedback"


class ClaimPolarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class ClaimModality(StrEnum):
    ASSERTED = "asserted"
    SPECULATIVE = "speculative"
    REPORTED = "reported"
    RUMOR = "rumor"
    QUESTION = "question"
    CRITICISM = "criticism"


class RelationType(StrEnum):
    MENTIONS = "mentions"
    PROPOSES = "proposes"
    IMPLEMENTS = "implements"
    DISCUSSES = "discusses"
    COMPARES = "compares"
    ADOPTS = "adopts"
    SUPPORTS = "supports"
    CRITICIZES = "criticizes"
    EXTENDS = "extends"
    SIMILAR_TO = "similar_to"
    SAME_TOPIC = "same_topic"


class RelationDirection(StrEnum):
    DIRECTED = "directed"
    UNDIRECTED = "undirected"


class MaturityStage(StrEnum):
    RESEARCH = "research"
    PROTOTYPE = "prototype"
    EARLY_ADOPTION = "early_adoption"
    PRODUCTIONIZING = "productionizing"
    MAINSTREAM = "mainstream"
    UNKNOWN = "unknown"


class TrendDirection(StrEnum):
    RISING = "rising"
    STABLE = "stable"
    FALLING = "falling"
    SPIKE = "spike"
    UNKNOWN = "unknown"


class ImpactArea(StrEnum):
    RESEARCH = "research"
    ENGINEERING = "engineering"
    PRODUCT = "product"
    ECOSYSTEM = "ecosystem"
    BUSINESS = "business"
    POLICY = "policy"
    COMMUNITY = "community"


class InsightType(StrEnum):
    TECHNOLOGY_EMERGENCE = "technology_emergence"
    PAPER_TO_PROJECT = "paper_to_project"
    PROJECT_TO_COMMUNITY = "project_to_community"
    NEWS_TO_TECHNOLOGY = "news_to_technology"
    COMMUNITY_SHIFT = "community_shift"
    MATURITY_CHANGE = "maturity_change"
    TREND_ALERT = "trend_alert"


class ReportType(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    TOPIC = "topic"
    TECHNOLOGY = "technology"
    BOARD = "board"
    CROSS_BOARD = "cross_board"


class ProcessingStatus(StrEnum):
    NEW = "new"
    NORMALIZED = "normalized"
    DEDUPLICATED = "deduplicated"
    EXTRACTED = "extracted"
    LINKED = "linked"
    ANALYZED = "analyzed"
    PUBLISHED = "published"
    REJECTED = "rejected"
    ERROR = "error"


class TaxonomyType(StrEnum):
    TECHNOLOGY = "technology"
    TOPIC = "topic"
    BOARD = "board"
    IMPACT_AREA = "impact_area"


class ObjectType(StrEnum):
    SIGNAL = "signal"
    ENTITY = "entity"
    TOPIC = "topic"
    TECHNOLOGY = "technology"
    CLAIM = "claim"
    PAPER = "paper"
    PROJECT = "project"
    COMMUNITY_THREAD = "community_thread"
    NEWS_ITEM = "news_item"


class RadarRecommendation(StrEnum):
    WATCH = "watch"
    INVESTIGATE = "investigate"
    ADOPT_CAREFULLY = "adopt_carefully"
    IGNORE_FOR_NOW = "ignore_for_now"
    HIGH_PRIORITY = "high_priority"


class DetailSectionType(StrEnum):
    SUMMARY = "summary"
    KEY_POINTS = "key_points"
    RELATED_PAPERS = "related_papers"
    RELATED_PROJECTS = "related_projects"
    RELATED_DISCUSSIONS = "related_discussions"
    RELATED_NEWS = "related_news"
    TECHNOLOGY_RADAR = "technology_radar"
    EVIDENCE = "evidence"
    CLAIMS = "claims"
    TIMELINE = "timeline"
    QUALITY_BREAKDOWN = "quality_breakdown"
    MATURITY_BREAKDOWN = "maturity_breakdown"
