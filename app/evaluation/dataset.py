import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Split = Literal["development", "test", "all"]


class GoldenCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    answerable: bool
    expected_answer: str = Field(min_length=1)
    expected_behavior: Literal["answer", "abstain", "clarify"] | None = None
    relevant_documents: list[str]
    relevant_pages: list[int | None]

    @model_validator(mode="after")
    def validate_sources(self):
        if self.expected_behavior == "answer" and not self.answerable:
            raise ValueError("answer behavior requires an answerable case")
        if self.expected_behavior == "clarify" and self.answerable:
            raise ValueError("clarify behavior requires an unanswerable case")
        if len(self.relevant_documents) != len(self.relevant_pages):
            raise ValueError("relevant_documents and relevant_pages must have equal length")
        if self.answerable and not self.relevant_documents:
            raise ValueError("answerable cases require at least one relevant source")
        if not self.answerable and (self.relevant_documents or self.relevant_pages):
            raise ValueError("unsupported cases cannot declare relevant sources")
        return self

    @property
    def expected_sources(self) -> set[tuple[str, int | None]]:
        return set(zip(self.relevant_documents, self.relevant_pages, strict=True))


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    corpus_version: str
    description: str
    development_ids: list[str]
    test_ids: list[str]
    coverage: dict[str, list[str]] = Field(default_factory=dict)


@dataclass(frozen=True)
class DatasetBundle:
    cases: list[GoldenCase]
    manifest: DatasetManifest
    dataset_sha256: str
    corpus_sha256: str
    split: Split


def _hash_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_dataset(project_root: Path, split: Split = "development") -> DatasetBundle:
    dataset_path = project_root / "evals/golden_dataset.json"
    manifest_path = project_root / "evals/dataset_manifest.json"
    raw_cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases = [GoldenCase.model_validate(case) for case in raw_cases]

    if manifest_path.exists():
        manifest = DatasetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = DatasetManifest(
            dataset_version="unversioned", corpus_version="unversioned",
            description="Legacy test fixture",
            development_ids=[case.id for case in cases], test_ids=[],
        )

    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("dataset case IDs must be unique")
    declared = manifest.development_ids + manifest.test_ids
    if len(declared) != len(set(declared)) or set(declared) != set(ids):
        raise ValueError("manifest splits must contain every case exactly once")
    unknown_coverage_ids = {
        case_id for values in manifest.coverage.values() for case_id in values
    } - set(ids)
    if unknown_coverage_ids:
        raise ValueError(f"coverage references unknown IDs: {sorted(unknown_coverage_ids)}")

    selected_ids = {
        "development": set(manifest.development_ids),
        "test": set(manifest.test_ids),
        "all": set(ids),
    }[split]
    selected = [case for case in cases if case.id in selected_ids]
    dataset_hash = (
        _hash_files([dataset_path, manifest_path])
        if manifest_path.exists()
        else hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    )
    corpus_files = [path for path in (project_root / "data/raw").glob("*") if path.is_file()]
    corpus_hash = _hash_files(corpus_files) if corpus_files else hashlib.sha256(b"").hexdigest()
    return DatasetBundle(selected, manifest, dataset_hash, corpus_hash, split)
