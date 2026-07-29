"""Typed models for the Document360 v2 API.

These model only the fields the sync job consumes. Several fields present in
the live API responses are deliberately omitted:

- ``authors`` / ``created_by`` — PII (names, emails of Preiss staff). No reason
  to carry these into the vector index.
- ``custom_fields`` / ``current_workflow_status_id`` — internal D360 workflow
  state, irrelevant to retrieval.
- profile/CDN logo URLs — signed, short-lived, useless to us.

All models use ``extra="ignore"`` so that new fields appearing in the API don't
break parsing.

Status / visibility semantics (confirmed against the live Preiss Central
instance):

- ``status``: integer. ``3`` = published. ``0`` = draft / unpublished edit
  (these typically have ``latest_version`` ahead of ``public_version``).
  Only ``status == 3`` should be indexed.
- ``hidden``: boolean. A published article can still be hidden in the KB
  (e.g. "Known Issues & Workarounds"). Hidden articles should NOT be indexed.
- ``security_visibility``: integer, observed values 0 and 1. Exact semantics
  unconfirmed — likely an access-level flag. Captured but NOT filtered on.
  Indexing a restricted-visibility article into a corpus everyone can query
  would be a leak, so this needs confirming before it's safe to ignore.
- ``content_type``: integer, observed 1 and 2. Likely markdown vs HTML-editor
  content. Captured and passed through; the chunking step downstream decides
  how to handle the body.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# D360 status code for a published article.
STATUS_PUBLISHED = 3


class _D360Model(BaseModel):
    """Base: ignore unknown fields so upstream additions don't break parsing."""

    model_config = ConfigDict(extra="ignore")


class LanguageVersion(_D360Model):
    """One language under a project version. ``code`` (e.g. "en") is the value
    the article-by-id endpoint needs as its language path segment."""

    id: str
    name: str
    code: str
    set_as_default: bool = False
    hidden: bool = False


class ProjectVersion(_D360Model):
    """A project version. Article listing is scoped to one of these."""

    id: str
    version_number: float | None = None
    version_code_name: str | None = None
    is_main_version: bool = False
    slug: str | None = None
    language_versions: list[LanguageVersion] = Field(default_factory=list)

    @property
    def default_language_code(self) -> str:
        """Best-effort default language code, falling back to "en"."""
        for lv in self.language_versions:
            if lv.set_as_default:
                return lv.code
        if self.language_versions:
            return self.language_versions[0].code
        return "en"


class ArticleStub(_D360Model):
    """Lightweight article metadata as it appears embedded in the category
    tree. Carries everything needed to decide what to (re)index without
    fetching the full body."""

    id: str
    title: str
    slug: str | None = None
    language_code: str = "en"
    status: int
    hidden: bool = False
    content_type: int | None = None
    security_visibility: int | None = None
    public_version: int | None = None
    latest_version: int | None = None
    modified_at: datetime
    # ``category_id`` is not part of the raw stub; the client sets it during the
    # tree walk so downstream code can tag chunks with their category.
    category_id: str | None = None

    @property
    def is_published(self) -> bool:
        return self.status == STATUS_PUBLISHED

    @property
    def is_indexable(self) -> bool:
        """Published AND not hidden. This is the filter the sync job applies."""
        return self.status == STATUS_PUBLISHED and not self.hidden


class Category(_D360Model):
    """A category node in the tree. Nests via ``child_categories`` and embeds
    its articles directly in ``articles`` — so the whole content tree can be
    enumerated from a single ``/ProjectVersions/{id}/categories`` call."""

    id: str
    name: str | None = None
    slug: str | None = None
    order: int | None = None
    parent_category_id: str | None = None
    hidden: bool = False
    articles: list[ArticleStub] = Field(default_factory=list)
    child_categories: list["Category"] = Field(default_factory=list)

    def iter_articles(self) -> list[ArticleStub]:
        """Flatten this category and all descendants into a list of article
        stubs, tagging each stub with the id of the category it came from."""
        out: list[ArticleStub] = []
        for article in self.articles:
            if article.category_id is None:
                article.category_id = self.id
            out.append(article)
        for child in self.child_categories:
            out.extend(child.iter_articles())
        return out


class Article(_D360Model):
    """Full article, as returned by the article-by-id endpoint. Includes the
    HTML body and the public URL used for citation links."""

    id: str
    title: str
    slug: str | None = None
    description: str | None = None
    html_content: str | None = ""
    content: str | None = ""
    status: int
    hidden: bool = False
    content_type: int | None = None
    security_visibility: int | None = None
    category_id: str | None = None
    project_version_id: str | None = None
    public_version: int | None = None
    latest_version: int | None = None
    modified_at: datetime
    # Public URL, e.g. https://preisscentral.com/docs/en/central-documents-list
    # Use this as the citation link when Molli answers from this article.
    url: str | None = None

    @property
    def is_published(self) -> bool:
        return self.status == STATUS_PUBLISHED

    @property
    def is_indexable(self) -> bool:
        return self.status == STATUS_PUBLISHED and not self.hidden

    @property
    def body(self) -> str:
        """The content to chunk/embed. Preiss Central articles carry their body
        in ``html_content`` (``content`` is typically empty); fall back to
        ``content`` if html is absent."""
        return self.html_content or self.content or ""


# Pydantic 2 resolves the forward reference in ``child_categories`` here.
Category.model_rebuild()
