"""Lexicon entry models — words, morphemes, and their metadata."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PartOfSpeech(str, Enum):
    """Grammatical part of speech."""

    NOUN = "noun"
    VERB = "verb"
    ADJECTIVE = "adjective"
    ADVERB = "adverb"
    PRONOUN = "pronoun"
    DETERMINER = "determiner"
    PREPOSITION = "preposition"
    POSTPOSITION = "postposition"
    CONJUNCTION = "conjunction"
    INTERJECTION = "interjection"
    PARTICLE = "particle"
    NUMERAL = "numeral"
    ROOT = "root"
    AFFIX = "affix"
    OTHER = "other"


class Register(str, Enum):
    """Sociolinguistic register (formality level)."""

    SACRED = "sacred"
    FORMAL = "formal"
    NEUTRAL = "neutral"
    COLLOQUIAL = "colloquial"
    TABOO = "taboo"


class LexemeEntry(BaseModel):
    """A single lexical entry in the dictionary.

    Attributes:
        id: Unique identifier (stable string, e.g. 'lex_spirit_001').
        form: ASCIIPA surface form.
        phonemic: Broad phonemic transcription (ASCIIPA with / /).
        gloss: Short meaning in the meta-language (e.g. English/Chinese).
        definition: Longer definition.
        pos: Part of speech.
        register: Sociolinguistic register.
        frequency: Usage frequency (0.0–1.0), affects sound change probability.
        semantic_field: Semantic domain (e.g. 'body_parts', 'kinship').
        etymology_id: Link to etymology record.
        examples: Example sentences using this word.
        notes: Free-form notes.
        tags: Arbitrary tags for filtering.
    """

    id: str = Field(description="Unique identifier")
    form: str = Field(description="ASCIIPA surface form")
    phonemic: str = Field(default="", description="Phonemic form (ASCIIPA)")
    gloss: str = Field(default="", description="Short meaning")
    definition: str = Field(default="", description="Full definition")
    pos: PartOfSpeech = PartOfSpeech.NOUN
    register_level: Register = Register.NEUTRAL
    frequency: float = Field(default=0.5, ge=0.0, le=1.0)
    semantic_field: str = Field(default="", description="Semantic domain")
    etymology_id: str = Field(default="", description="Link to etymology record")
    examples: list[str] = Field(default_factory=list)
    notes: str = ""
    tags: list[str] = Field(default_factory=list)


class CognateSet(BaseModel):
    """A set of cognate words across related languages/dialects.

    Attributes:
        id: Unique identifier.
        proto_form: Reconstructed proto-form (ASCIIPA).
        proto_gloss: Meaning of the proto-form.
        descendants: Dict of language_id → LexemeEntry.id.
    """

    id: str
    proto_form: str = Field(description="Proto-form in ASCIIPA")
    proto_gloss: str = ""
    descendants: dict[str, str] = Field(
        default_factory=dict,
        description="language_id → lexeme_id mapping",
    )
