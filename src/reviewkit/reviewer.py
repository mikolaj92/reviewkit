"""Hierarchical reviewer orchestration."""

from __future__ import annotations

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
    ) -> None:
        self.profile = profile
        self.llm = llm
        self.context_provider = context_provider or EmptyReviewContextProvider()

    def review(
        self, document: ReviewDocument
    ) -> tuple[list[ReviewFinding], list[ReviewAction], ReviewState]:
        state = ReviewState()
        findings: list[ReviewFinding] = []
        actions: list[ReviewAction] = []
        section_level_actions: list[ReviewAction] = []
        pipeline = set(self.profile.review_pipeline)

        for section in document.sections:
            paragraph_level_actions: list[ReviewAction] = []

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
                        findings.extend(sentence_response.findings)
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
                    findings.extend(paragraph_response.findings)
                    paragraph_level_actions.extend(paragraph_response.actions)
                    actions.extend(paragraph_response.actions)

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
                        paragraph_level_actions,
                        context,
                    ),
                    SectionReviewResponse,
                    state=state,
                    label=f"section {section.id}",
                )
                section_response = self._prepare_response(document, section_response)
                state.absorb_response(ReviewScope.SECTION, section.id, section_response)
                findings.extend(section_response.findings)
                section_level_actions.extend(section_response.actions)
                actions.extend(section_response.actions)

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
                    section_level_actions,
                    context,
                ),
                DocumentReviewResponse,
                state=state,
                label="document",
            )
            document_response = self._prepare_response(document, document_response)
            state.absorb_response(ReviewScope.DOCUMENT, document.id, document_response)
            findings.extend(document_response.findings)
            actions.extend(document_response.actions)

        return findings, actions, state

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
            if isinstance(raw, BaseModel):
                return schema.model_validate(raw.model_dump(mode="json"))
            return schema.model_validate(raw)
        except Exception as error:
            # Resilience: a single failing node (client error or malformed/invalid
            # response) must not abort the whole review. Skip this node with an empty
            # response and surface the failure as a warning so callers can react.
            state.warnings.append(
                f"LLM review skipped for {label}: {type(error).__name__}: {error}"
            )
            return schema()

    def _prepare_response[T: ReviewResponse](
        self,
        document: ReviewDocument,
        response: T,
    ) -> T:
        actions = prepare_actions(document, self.profile, response.actions)
        return response.model_copy(update={"actions": actions})
