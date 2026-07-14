"""Immutable source fragments, explicit relations, and safe projections."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from ..research_store import canonical_json
from .models import FrozenModel
from .sources import Sha256, SourceManifest


ContentRole = Literal[
    "root_text", "translation", "commentary", "school_interpretation", "worked_case"
]
AdmissionStatus = Literal["admitted", "quarantined", "rejected"]
ExcerptPermission = Literal["none", "short_quote", "public_domain"]
RelationType = Literal[
    "translation_of",
    "commentary_on",
    "agrees_with",
    "contradicts",
    "scoped_to",
    "supersedes",
]


class EvidenceFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class FragmentDraft(FrozenModel):
    source_id: str = Field(min_length=3, max_length=96)
    source_manifest_sha256: Sha256
    page_number: int = Field(ge=1)
    printed_page: int
    anchor_kind: Literal["page", "heading", "sutra", "verse", "case"]
    anchor_label: str = Field(min_length=1, max_length=160)
    language: str = Field(min_length=2, max_length=32)
    content_role: ContentRole
    school: str = Field(min_length=1, max_length=120)
    scope: str = Field(min_length=1, max_length=120)
    full_text_sha256: Sha256
    normalized_content_sha256: Sha256
    excerpt_permission: ExcerptPermission
    permitted_excerpt: str | None = Field(default=None, max_length=4_000)
    admission_status: AdmissionStatus

    @model_validator(mode="after")
    def _permitted_excerpt_contract(self) -> "FragmentDraft":
        if self.excerpt_permission == "none" and self.permitted_excerpt is not None:
            raise ValueError("none permission cannot retain an excerpt")
        if self.excerpt_permission != "none" and not self.permitted_excerpt:
            raise ValueError("permitted excerpt is required for exportable text")
        if (
            self.excerpt_permission == "short_quote"
            and self.permitted_excerpt is not None
            and len(self.permitted_excerpt) > 600
        ):
            raise ValueError("short_quote permitted excerpts are limited to 600 characters")
        return self


class SourceFragment(FrozenModel):
    fragment_id: str = Field(pattern=r"^frag_[0-9a-f]{24}$")
    revision: int = Field(ge=1)
    revision_sha256: Sha256
    draft_sha256: Sha256
    source_id: str
    source_manifest_sha256: Sha256
    source_file_sha256: Sha256
    page_number: int
    printed_page: int
    anchor_kind: str
    anchor_label: str
    language: str
    content_role: ContentRole
    school: str
    scope: str
    full_text_sha256: Sha256
    normalized_content_sha256: Sha256
    excerpt_permission: ExcerptPermission
    permitted_excerpt: str | None
    admission_status: AdmissionStatus


class FragmentRef(FrozenModel):
    fragment_id: str = Field(pattern=r"^frag_[0-9a-f]{24}$")
    revision: int = Field(ge=1)
    revision_sha256: Sha256

    @classmethod
    def from_fragment(cls, fragment: SourceFragment) -> "FragmentRef":
        return cls(
            fragment_id=fragment.fragment_id,
            revision=fragment.revision,
            revision_sha256=fragment.revision_sha256,
        )


class FragmentRelation(FrozenModel):
    relation_id: str = Field(pattern=r"^rel_[0-9a-f]{24}$")
    source: FragmentRef
    target: FragmentRef
    relation_type: RelationType
    scope: str | None = Field(default=None, max_length=160)


class PublicFragment(FrozenModel):
    source_id: str
    printed_page: int
    anchor_kind: str
    anchor_label: str
    language: str
    content_role: ContentRole
    school: str
    scope: str
    permitted_excerpt: str | None
    admission_status: AdmissionStatus


class InspectionFragment(PublicFragment):
    fragment_id: str
    revision: int
    revision_sha256: Sha256
    source_manifest_sha256: Sha256
    source_file_sha256: Sha256
    full_text_sha256: Sha256
    normalized_content_sha256: Sha256
    excerpt_permission: ExcerptPermission


class EvidenceStore:
    """Append-only in-memory core; deterministic snapshots are persistence-neutral."""

    def __init__(self, manifest: SourceManifest) -> None:
        self.manifest = manifest
        self._source_by_id = {source.source_id: source for source in manifest.sources}
        self._fragments: dict[str, list[SourceFragment]] = {}
        self._relations: dict[str, FragmentRelation] = {}

    def append(self, draft: FragmentDraft) -> SourceFragment:
        if draft.source_manifest_sha256 != self.manifest.manifest_sha256:
            raise EvidenceFailure(
                "SOURCE_MANIFEST_SUBSTITUTED",
                "Fragment source manifest does not match the active evidence store.",
            )
        source = self._source_by_id.get(draft.source_id)
        if source is None:
            raise EvidenceFailure("SOURCE_UNKNOWN", "Fragment source is not in the manifest.")
        draft_payload = draft.model_dump(mode="json")
        draft_sha256 = _hash_payload(draft_payload)
        fragment_id = _fragment_id(draft)
        history = self._fragments.setdefault(fragment_id, [])
        if history and history[-1].draft_sha256 == draft_sha256:
            return history[-1]
        revision = len(history) + 1
        revision_payload = {
            "fragment_id": fragment_id,
            "revision": revision,
            "draft_sha256": draft_sha256,
            "source_file_sha256": source.sha256,
            **draft_payload,
        }
        fragment = SourceFragment(
            **revision_payload,
            revision_sha256=_hash_payload(revision_payload),
        )
        previous = history[-1] if history else None
        history.append(fragment)
        if previous is not None:
            self._relate_refs(
                FragmentRef.from_fragment(fragment),
                FragmentRef.from_fragment(previous),
                "supersedes",
                scope=draft.scope,
            )
        return fragment

    def relate(
        self,
        source: SourceFragment,
        target: SourceFragment,
        relation_type: RelationType,
        *,
        scope: str | None = None,
    ) -> FragmentRelation:
        source_ref = FragmentRef.from_fragment(source)
        target_ref = FragmentRef.from_fragment(target)
        self.resolve(source_ref)
        self.resolve(target_ref)
        if source_ref == target_ref:
            raise EvidenceFailure("RELATION_SELF_REFERENCE", "A fragment cannot relate to itself.")
        return self._relate_refs(source_ref, target_ref, relation_type, scope=scope)

    def _relate_refs(
        self,
        source: FragmentRef,
        target: FragmentRef,
        relation_type: RelationType,
        *,
        scope: str | None,
    ) -> FragmentRelation:
        payload = {
            "source": source.model_dump(mode="json"),
            "target": target.model_dump(mode="json"),
            "relation_type": relation_type,
            "scope": scope,
        }
        relation = FragmentRelation(
            relation_id=f"rel_{_hash_payload(payload)[:24]}",
            **payload,
        )
        self._relations.setdefault(relation.relation_id, relation)
        return self._relations[relation.relation_id]

    def resolve(
        self, reference: FragmentRef, *, require_current: bool = False
    ) -> SourceFragment:
        history = self._fragments.get(reference.fragment_id)
        if not history or reference.revision > len(history):
            raise EvidenceFailure("SOURCE_FRAGMENT_MISSING", "Source fragment is missing.")
        fragment = history[reference.revision - 1]
        if fragment.revision_sha256 != reference.revision_sha256:
            raise EvidenceFailure(
                "SOURCE_FRAGMENT_SUBSTITUTED",
                "Source fragment revision hash does not match stored evidence.",
            )
        if require_current and fragment.revision != history[-1].revision:
            raise EvidenceFailure(
                "SOURCE_FRAGMENT_STALE", "Source fragment revision is no longer current."
            )
        return fragment

    def lookup(
        self,
        query: str,
        *,
        limit: int,
        projection: Literal["public", "inspection"],
    ) -> tuple[PublicFragment | InspectionFragment, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        needle = " ".join(query.casefold().split())
        candidates: list[SourceFragment] = []
        for fragment_id in sorted(self._fragments):
            history = self._fragments[fragment_id]
            revisions = history if projection == "inspection" else history[-1:]
            for fragment in revisions:
                if projection == "public" and fragment.admission_status != "admitted":
                    continue
                haystack = " ".join(
                    part
                    for part in (
                        fragment.source_id,
                        fragment.anchor_label,
                        fragment.school,
                        fragment.scope,
                        fragment.permitted_excerpt or "",
                    )
                ).casefold()
                if not needle or needle in haystack:
                    candidates.append(fragment)
        candidates.sort(
            key=lambda item: (
                item.source_id,
                item.printed_page,
                item.anchor_label,
                item.fragment_id,
                item.revision,
            )
        )
        return tuple(self._project(item, projection) for item in candidates[:limit])

    @staticmethod
    def _project(
        fragment: SourceFragment, projection: Literal["public", "inspection"]
    ) -> PublicFragment | InspectionFragment:
        public = {
            "source_id": fragment.source_id,
            "printed_page": fragment.printed_page,
            "anchor_kind": fragment.anchor_kind,
            "anchor_label": fragment.anchor_label,
            "language": fragment.language,
            "content_role": fragment.content_role,
            "school": fragment.school,
            "scope": fragment.scope,
            "permitted_excerpt": fragment.permitted_excerpt,
            "admission_status": fragment.admission_status,
        }
        if projection == "public":
            return PublicFragment(**public)
        return InspectionFragment(
            **public,
            fragment_id=fragment.fragment_id,
            revision=fragment.revision,
            revision_sha256=fragment.revision_sha256,
            source_manifest_sha256=fragment.source_manifest_sha256,
            source_file_sha256=fragment.source_file_sha256,
            full_text_sha256=fragment.full_text_sha256,
            normalized_content_sha256=fragment.normalized_content_sha256,
            excerpt_permission=fragment.excerpt_permission,
        )

    @property
    def fragments(self) -> tuple[SourceFragment, ...]:
        return tuple(
            fragment
            for fragment_id in sorted(self._fragments)
            for fragment in self._fragments[fragment_id]
        )

    def admitted_catalog(self, *, limit: int) -> tuple[FragmentRef, ...]:
        """Return bounded current evidence identities for doctrine compilation."""
        if isinstance(limit, bool) or not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        admitted = [
            FragmentRef.from_fragment(history[-1])
            for _, history in sorted(self._fragments.items())
            if history[-1].admission_status == "admitted"
        ]
        return tuple(admitted[:limit])

    @property
    def relations(self) -> tuple[FragmentRelation, ...]:
        return tuple(self._relations[key] for key in sorted(self._relations))

    @property
    def store_sha256(self) -> str:
        return _hash_payload(
            {
                "source_manifest_sha256": self.manifest.manifest_sha256,
                "fragments": [item.model_dump(mode="json") for item in self.fragments],
                "relations": [item.model_dump(mode="json") for item in self.relations],
            }
        )

    def export_permitted(self) -> dict[str, object]:
        current = [
            history[-1]
            for fragment_id, history in sorted(self._fragments.items())
            if history[-1].admission_status == "admitted"
        ]
        fragments: list[dict[str, object]] = []
        current_refs = {FragmentRef.from_fragment(item) for item in current}
        for fragment in current:
            payload = self._project(fragment, "public").model_dump(mode="json")
            if fragment.excerpt_permission == "none":
                payload["permitted_excerpt"] = None
            fragments.append(payload)
        relations = [
            relation.model_dump(mode="json")
            for relation in self.relations
            if relation.source in current_refs and relation.target in current_refs
        ]
        return {
            "schema_version": "1.0",
            "source_manifest_sha256": self.manifest.manifest_sha256,
            "store_sha256": self.store_sha256,
            "fragments": fragments,
            "relations": relations,
        }


def _fragment_id(draft: FragmentDraft) -> str:
    identity = {
        "source_id": draft.source_id,
        "page_number": draft.page_number,
        "anchor_kind": draft.anchor_kind,
        "anchor_label": draft.anchor_label,
        "language": draft.language,
        "content_role": draft.content_role,
        "school": draft.school,
        "scope": draft.scope,
    }
    return f"frag_{_hash_payload(identity)[:24]}"


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
