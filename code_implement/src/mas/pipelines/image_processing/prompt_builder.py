"""Build prompts and load IPA taxonomy."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import json
from pathlib import Path
from typing import Any

from .context_builder import ImageContext
from .image_reference import ResolvedImage
from .markdown_parser import MarkdownImage


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


@dataclass
class TaxonomyItem:
    id: str
    label: str
    default_kg_value: str
    rule: str


@dataclass
class ImageTaxonomy:
    version: str
    items: list[TaxonomyItem]

    @property
    def type_ids(self) -> set[str]:
        return {item.id for item in self.items}

    def as_prompt_text(self) -> str:
        return "\n".join(
            f"- {item.id}: {item.label}; default={item.default_kg_value}; rule={item.rule}"
            for item in self.items
        )


@dataclass
class PromptPackage:
    batch_id: str
    round_name: str
    system_prompt: str
    user_prompt: str
    template_version: str
    metadata: dict[str, Any]


def load_taxonomy(path: Path | None = None) -> ImageTaxonomy:
    taxonomy_path = path or PROMPT_DIR / "image_taxonomy.json"
    data = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    return ImageTaxonomy(
        version=str(data.get("version", "ipa.taxonomy.v1")),
        items=[TaxonomyItem(**item) for item in data.get("items", [])],
    )


def _read_prompt(name: str, prompt_dir: Path | None = None) -> str:
    return ((prompt_dir or PROMPT_DIR) / name).read_text(encoding="utf-8")


def build_round1_prompt(
    batch_id: str,
    images: list[tuple[MarkdownImage, ResolvedImage, ImageContext]],
    taxonomy: ImageTaxonomy,
    prompt_dir: Path | None = None,
) -> PromptPackage:
    system_prompt = _read_prompt("ipa_round1_system.txt", prompt_dir)
    template = _read_prompt("ipa_round1_user_template.txt", prompt_dir)
    image_payload = []
    for image, resolved, context in images:
        image_payload.append(
            {
                "image_id": image.image_id,
                "image_link": image.raw_link,
                "image_path": str(resolved.resolved_path),
                "image_exists": resolved.exists,
                "file_name": resolved.file_name,
                "suffix": resolved.suffix,
                "section_title": context.section_title,
                "nearest_heading": context.nearest_heading,
                "before_context": context.before_blocks,
                "after_context": context.after_blocks,
            }
        )
    user_prompt = template.format(
        taxonomy_version=taxonomy.version,
        taxonomy=taxonomy.as_prompt_text(),
        batch_id=batch_id,
        images_json=json.dumps(image_payload, ensure_ascii=False, indent=2),
    )
    return PromptPackage(
        batch_id=batch_id,
        round_name="tagging",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        template_version="ipa.round1.prompt.v1",
        metadata={
            "taxonomy_version": taxonomy.version,
            "image_ids": [item[0].image_id for item in images],
            "images": [
                {
                    "image_id": image.image_id,
                    "image_path": str(resolved.resolved_path),
                    "image_exists": resolved.exists,
                }
                for image, resolved, _context in images
            ],
        },
    )


def build_round2_prompt(
    batch_id: str,
    image: MarkdownImage,
    resolved: ResolvedImage,
    context: ImageContext,
    tag: Any,
    revision_feedback: str = "",
    output_mode_hint: str = "",
    prompt_dir: Path | None = None,
) -> PromptPackage:
    system_prompt = _read_prompt("ipa_round2_system.txt", prompt_dir)
    template = _read_prompt("ipa_round2_user_template.txt", prompt_dir)
    user_prompt = template.format(
        batch_id=batch_id,
        image_id=image.image_id,
        image_link=image.raw_link,
        image_path=str(resolved.resolved_path),
        image_exists=resolved.exists,
        section_title=context.section_title,
        nearest_heading=context.nearest_heading,
        before_context="\n\n".join(context.before_blocks),
        after_context="\n\n".join(context.after_blocks),
        image_type_id=getattr(tag, "image_type_id", ""),
        kg_value=getattr(tag, "kg_value", ""),
        revision_feedback=revision_feedback,
        output_mode_hint=output_mode_hint,
    )
    return PromptPackage(
        batch_id=batch_id,
        round_name="textualization",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        template_version="ipa.round2.prompt.v1",
        metadata={
            "image_id": image.image_id,
            "images": [
                {
                    "image_id": image.image_id,
                    "image_path": str(resolved.resolved_path),
                    "image_exists": resolved.exists,
                }
            ],
        },
    )


def build_verify_prompt(
    batch_id: str,
    image: MarkdownImage,
    resolved: ResolvedImage,
    context: ImageContext,
    tag: Any,
    candidate: Any,
    round_index: int,
    prompt_dir: Path | None = None,
) -> PromptPackage:
    system_prompt = _read_prompt("ipa_verify_system.txt", prompt_dir)
    template = _read_prompt("ipa_verify_user_template.txt", prompt_dir)
    candidate_payload = asdict(candidate) if is_dataclass(candidate) else candidate
    candidate_json = json.dumps(candidate_payload, ensure_ascii=False, indent=2)
    user_prompt = template.format(
        image_id=image.image_id,
        image_type_id=getattr(tag, "image_type_id", ""),
        kg_value=getattr(tag, "kg_value", ""),
        round_index=round_index,
        candidate_json=candidate_json,
        section_title=context.section_title,
        nearest_heading=context.nearest_heading,
    )
    return PromptPackage(
        batch_id=batch_id,
        round_name="verification",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        template_version="ipa.verify.prompt.v1",
        metadata={
            "image_id": image.image_id,
            "round_index": round_index,
            "images": [
                {
                    "image_id": image.image_id,
                    "image_path": str(resolved.resolved_path),
                    "image_exists": resolved.exists,
                }
            ],
        },
    )
