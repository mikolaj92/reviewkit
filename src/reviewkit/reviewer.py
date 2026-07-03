"""Hierarchical reviewer orchestration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from reviewkit.actions import prepare_actions
from reviewkit.context import EmptyReviewContextProvider, ReviewContextProvider
from reviewkit.document import ReviewDocument
from reviewkit.llm import LLMClient
from reviewkit.models import (
    DocumentReviewResponse,
    ParagraphReviewResponse,
    ReviewAction,
    ReviewFinding,
    ReviewResponse,
    ReviewScope,
    SectionReviewResponse,
    SentenceReviewResponse,
)
from reviewkit.policy import ActionPolicy
from reviewkit.profile import ReviewProfile
from reviewkit.prompts import (
    document_review_prompt,
    paragraph_review_prompt,
    section_review_prompt,
    sentence_review_prompt,
)
from reviewkit.state import ReviewState


class HierarchicalReviewer:
    def __init__(
        self,
        profile: ReviewProfile,
        llm: LLMClient,
        context_provider: ReviewContextProvider | None = None,
        action_policy: ActionPolicy | None = None,
    ) -> None:
        self.profile = profile
        self.llm = llm
        self.context_provider = context_provider or EmptyReviewContextProvider()
        # An injected policy is the peer of ``context_provider``: callers can supply
        # programmatic fail-closed guards, not just regex config. None => build the
        # config-only policy from the profile per node.
        self.action_policy = action_policy

    def review(
        self, document: ReviewDocument
    ) -> tuple[list[ReviewFinding], list[ReviewAction], ReviewState]:
        state = ReviewState()
        actions: list[ReviewAction] = []
        # Lower-level actions roll up to the next ENABLED scope, not merely the adjacent
        # one, so a subset pipeline (e.g. sentence + document) still lets each higher
        # level see the results below it. ``document_input_actions`` is what document
        # review will see; ``section_input_actions`` (reset per section) is what section
        # review will see.
        document_input_actions: list[ReviewAction] = []
        pipeline = set(self.profile.review_pipeline)

        for section in document.sections:
            section_input_actions: list[ReviewAction] = []

            for paragraph in section.paragraphs:
                sentence_level_actions: list[ReviewAction] = []

                if ReviewScope.SENTENCE in pipeline:
                    for sentence in paragraph.sentences:
                        context = self.context_provider.context_for(
                            profile=self.profile,
                            document=document,
                            state=state,
                            scope=ReviewScope.SENTENCE,
                            node=sentence,
                        )
                        sentence_response = self._complete(
                            sentence_review_prompt(self.profile, state, sentence, context),
                            SentenceReviewResponse,
                            state=state,
                            label=f"sentence {sentence.id}",
                        )
                        sentence_response = self._prepare_response(document, sentence_response)
                        state.absorb_response(ReviewScope.SENTENCE, sentence.id, sentence_response)
                        sentence_level_actions.extend(sentence_response.actions)
                        actions.extend(sentence_response.actions)

                if ReviewScope.PARAGRAPH in pipeline:
                    context = self.context_provider.context_for(
                        profile=self.profile,
                        document=document,
                        state=state,
                        scope=ReviewScope.PARAGRAPH,
                        node=paragraph,
                    )
                    paragraph_response = self._complete(
                        paragraph_review_prompt(
                            self.profile,
                            state,
                            paragraph,
                            sentence_level_actions,
                            context,
                        ),
                        ParagraphReviewResponse,
                        state=state,
                        label=f"paragraph {paragraph.id}",
                    )
                    paragraph_response = self._prepare_response(document, paragraph_response)
                    state.absorb_response(ReviewScope.PARAGRAPH, paragraph.id, paragraph_response)
                    section_input_actions.extend(paragraph_response.actions)
                    actions.extend(paragraph_response.actions)
                else:
                    # Paragraph scope skipped: hand this paragraph's sentence results up
                    # to the next enabled scope rather than dropping them.
                    section_input_actions.extend(sentence_level_actions)

            if ReviewScope.SECTION in pipeline:
                context = self.context_provider.context_for(
                    profile=self.profile,
                    document=document,
                    state=state,
                    scope=ReviewScope.SECTION,
                    node=section,
                )
                section_response = self._complete(
                    section_review_prompt(
                        self.profile,
                        state,
                        section,
                        section_input_actions,
                        context,
                    ),
                    SectionReviewResponse,
                    state=state,
                    label=f"section {section.id}",
                )
                section_response = self._prepare_response(document, section_response)
                state.absorb_response(ReviewScope.SECTION, section.id, section_response)
                document_input_actions.extend(section_response.actions)
                actions.extend(section_response.actions)
            else:
                # Section scope skipped: roll this section's lower-level results up to
                # the document review.
                document_input_actions.extend(section_input_actions)

        if ReviewScope.DOCUMENT in pipeline:
            context = self.context_provider.context_for(
                profile=self.profile,
                document=document,
                state=state,
                scope=ReviewScope.DOCUMENT,
                node=document,
            )
            document_response = self._complete(
                document_review_prompt(
                    self.profile,
                    state,
                    document,
                    document_input_actions,
                    context,
                ),
                DocumentReviewResponse,
                state=state,
                label="document",
            )
            document_response = self._prepare_response(document, document_response)
            state.absorb_response(ReviewScope.DOCUMENT, document.id, document_response)
            actions.extend(document_response.actions)

        # ``state.findings`` is the single, deduplicated source of truth.
        return state.findings, actions, state

    def _complete[T: ReviewResponse](
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        *,
        state: ReviewState,
        label: str,
    ) -> T:
        try:
            raw = self.llm.complete_json(messages=messages, schema=schema)
        except Exception as error:
            # Resilience: a failing client call (network/API error) must not abort the
            # whole review. Skip this node with an empty response and surface the failure
            # as a warning so callers can react.
            state.warnings.append(
                f"LLM review skipped for {label}: {type(error).__name__}: {error}"
            )
            return schema()

        payload = raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
        return _validate_response_leniently(schema, payload, state=state, label=label)

    def _prepare_response[T: ReviewResponse](
        self,
        document: ReviewDocument,
        response: T,
    ) -> T:
        actions = prepare_actions(
            document, self.profile, response.actions, policy=self.action_policy
        )
        return response.model_copy(update={"actions": actions})


def _validate_response_leniently[T: ReviewResponse](
    schema: type[T],
    payload: Any,
    *,
    state: ReviewState,
    label: str,
) -> T:
    """Validate a review response, salvaging partial content on per-item failures.

    Real LLMs routinely emit one out-of-spec item among many good ones. Validating
    the whole response atomically would drop every valid finding, the summary, and
    every other valid action over a single bad field -- the opposite of the
    resilience intent. So validate ``actions`` and ``findings`` item by item and
    drop only the individually invalid ones (each surfaced as a warning), while the
    surrounding fields (summary, risks, ...) validate independently.
    """
    if not isinstance(payload, dict):
        try:
            return schema.model_validate(payload)
        except Exception as error:
            state.warnings.append(
                f"LLM review response invalid for {label}: {type(error).__name__}: {error}"
            )
            return schema()

    body = dict(payload)
    raw_actions = body.pop("actions", None)
    raw_findings = body.pop("findings", None)
    try:
        response = schema.model_validate(body)
    except Exception as error:
        state.warnings.append(
            f"LLM review response fields invalid for {label}: {type(error).__name__}: {error}"
        )
        response = schema()

    return response.model_copy(
        update={
            "actions": _validate_items(ReviewAction, raw_actions, state, label, "action"),
            "findings": _validate_items(ReviewFinding, raw_findings, state, label, "finding"),
        }
    )


def _validate_items[M: BaseModel](
    model: type[M],
    items: Any,
    state: ReviewState,
    label: str,
    kind: str,
) -> list[M]:
    if items is None:
        return []
    if not isinstance(items, list):
        state.warnings.append(f"Dropped malformed {kind} list for {label}: expected a list")
        return []
    valid: list[M] = []
    for index, item in enumerate(items):
        try:
            valid.append(model.model_validate(item))
        except Exception as error:
            state.warnings.append(
                f"Dropped malformed {kind} {index} for {label}: {type(error).__name__}: {error}"
            )
    return valid
