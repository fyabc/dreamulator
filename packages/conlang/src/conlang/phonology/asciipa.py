"""ASCIIPA — ASCII-native phonetic alphabet encoding.

ASCIIPA (/æˈskiːpə/) is a domain-specific language for representing IPA
phonetic notation using only standard ASCII characters. It uses escape-based
modifiers, brace-macro containers, and LaTeX-style superscript/subscript syntax.

Syntax summary:
    - Base characters: a-z (direct IPA mapping)
    - Brace macros: {sh}=ʃ, {ng}=ŋ, {th}=θ, etc.
    - Small caps: I=ɪ, U=ʊ, E=ɛ, O=ɔ, A=ɑ, B=ʙ, G=ɢ, etc.
    - Escape/turned: \\a=ɐ, \\e=ə, \\v=ʌ, \\m=ɯ, \\r=ɹ, etc.
    - Mirror: <e=ɘ, <A=ɒ
    - Superscript (^): ^h=ʰ, ^w=ʷ, ^j=ʲ
    - Subscript (_): _o=voiceless, _v=voiced, _t=dental
    - Nasalization (~): a~=ã
    - Ejective/implosive ('): k'=kʼ, <b=ɓ
    - Syllable dot (.): ka.ta
    - Stress (!): !ba.na
    - Length (:): a:
    - Tone digits: ma5, ma55
    - Retroflex (>): t>=ʈ, d>=ɖ
    - Barred (=): i==ɨ, u==ʉ
    - @bind directives for scope isolation
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Token pattern — the heart of ASCIIPA lexical analysis
# ---------------------------------------------------------------------------
# Matches, in order of priority:
#   1. Brace macros:       {sh}, {ng}, {!}, etc.
#   2. Turned bases:       \a, \e, \v, \m, \r, \h, \w, \y + modifiers
#   3. Implosive/mirror:   <b, <d, <g, <e, <A + modifiers
#   4. Lateral click:      ||
#   5. Single-char base:   a-zA-Z, |, = + modifier chain (^h, _o, ~, ', >)
#   6. Structural tokens:  syllable dot (.), tone (:NN), stress (!), directives
TOKEN_PATTERN = re.compile(
    r"""
    (
    \{[^}]+\}                               # 1. brace macro
    |\\[a-zA-Z](?:[\^_~'>][a-zA-Z0-9]*)*    # 2. turned base + modifiers
    |<[a-zA-Z](?:[\^_~'>][a-zA-Z0-9]*)*     # 3. implosive/mirror + modifiers
    |\|\|                                    # 4. lateral click
    |[a-zA-Z|=](?:[\^_~'>][a-zA-Z0-9]*)*    # 5. single base + modifiers
    |!                                       # 6a. stress marker (always)
    |:[0-9]+                                 # 6b. tone/length
    |\.[0-9]*                                # 6c. syllable dot
    |@[a-z]+                                 # 6d. directives
    )
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Token:
    """An indivisible ASCIIPA token (one phoneme or structural marker)."""

    raw: str
    base: str = ""
    modifiers: tuple[str, ...] = ()
    is_macro: bool = False
    is_structural: bool = False

    def __str__(self) -> str:
        return self.raw


class ASCIIPATokenizer:
    """Tokenize ASCIIPA strings into indivisible Token objects.

    The tokenizer ensures that multi-character constructs like ``{sh}`` or
    ``p^h`` are treated as single units, preventing regex-based SCA rules
    from accidentally modifying internal characters.
    """

    def tokenize(self, text: str) -> list[Token]:
        """Break an ASCIIPA string into a list of Tokens.

        Args:
            text: ASCIIPA-encoded string.

        Returns:
            List of Token objects.
        """
        raw_tokens = TOKEN_PATTERN.findall(text)
        result: list[Token] = []
        for raw in raw_tokens:
            result.append(self._parse_token(raw))
        return result

    def detokenize(self, tokens: list[Token]) -> str:
        """Reconstruct an ASCIIPA string from tokens.

        Args:
            tokens: List of Token objects.

        Returns:
            ASCIIPA-encoded string.
        """
        return " ".join(tok.raw for tok in tokens)

    def _parse_token(self, raw: str) -> Token:
        """Parse a raw string into a Token."""
        # Brace macro (must be checked before structural markers)
        if raw.startswith("{") and raw.endswith("}"):
            return Token(raw=raw, base=raw, is_macro=True)

        # Structural markers
        if raw.startswith(".") or raw.startswith(":"):
            return Token(raw=raw, base=raw, is_structural=True)
        if raw.startswith("@"):
            return Token(raw=raw, base=raw, is_structural=True)
        if raw == "!":
            return Token(raw=raw, base="!", is_structural=True)

        # Lateral click
        if raw == "||":
            return Token(raw=raw, base="||", modifiers=())

        # Turned base: \a, \e, etc.
        if raw.startswith("\\") and len(raw) >= 2:
            base = raw[:2]  # e.g. '\a'
            modifiers = self._extract_modifiers(raw[2:])
            return Token(raw=raw, base=base, modifiers=modifiers)

        # Implosive/mirror base: <b, <d, <e, etc.
        if raw.startswith("<") and len(raw) >= 2:
            base = raw[:2]  # e.g. '<b'
            modifiers = self._extract_modifiers(raw[2:])
            return Token(raw=raw, base=base, modifiers=modifiers)

        # Single-char base + modifier chain
        base = raw[0]
        modifiers = self._extract_modifiers(raw[1:])
        return Token(raw=raw, base=base, modifiers=modifiers)

    @staticmethod
    def _extract_modifiers(suffix: str) -> tuple[str, ...]:
        """Extract modifier segments from a token suffix.

        E.g. ``^h_o~`` → ``('^h', '_o', '~')``
        """
        if not suffix:
            return ()
        mods: list[str] = []
        i = 0
        _STOP = frozenset("^_~'>")
        while i < len(suffix):
            ch = suffix[i]
            if ch in ("^", "_"):
                # Superscript or subscript: grab the marker + following alphanumerics
                j = i + 1
                while j < len(suffix) and suffix[j] not in _STOP:
                    j += 1
                mods.append(suffix[i:j])
                i = j
            elif ch in ("~", "'", ">"):
                mods.append(ch)
                i += 1
            else:
                # Bare character
                mods.append(ch)
                i += 1
        return tuple(mods)


# ---------------------------------------------------------------------------
# IPA ↔ ASCIIPA conversion (stub — full implementation in ipa_table.py)
# ---------------------------------------------------------------------------

def ipa_to_asciipa(ipa: str) -> str:
    """Convert an IPA string to ASCIIPA notation.

    Args:
        ipa: IPA string (Unicode).

    Returns:
        ASCIIPA-encoded string.
    """
    from conlang.phonology.ipa_table import IPA_TO_ASCIIPA_MAP

    result: list[str] = []
    i = 0
    while i < len(ipa):
        ch = ipa[i]
        # Strip brackets
        if ch in "[]/":
            i += 1
            continue
        mapped = IPA_TO_ASCIIPA_MAP.get(ch)
        if mapped:
            result.append(mapped)
        elif ch == " ":
            pass  # skip spaces (not meaningful in IPA)
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def asciipa_to_ipa(asciipa_str: str) -> str:
    """Convert an ASCIIPA string to IPA notation.

    Decomposes tokens into base + modifiers and converts each part
    separately, then concatenates the results.

    Args:
        asciipa_str: ASCIIPA-encoded string.

    Returns:
        IPA string (Unicode).
    """
    from conlang.phonology.ipa_table import ASCIIPA_TO_IPA_MAP

    tokenizer = ASCIIPATokenizer()
    tokens = tokenizer.tokenize(asciipa_str)
    result: list[str] = []
    for tok in tokens:
        if tok.is_structural:
            if tok.raw == ".":
                result.append(".")
            elif tok.raw == ":":
                result.append("ː")
            elif tok.raw.startswith("!"):
                result.append("ˈ")
            else:
                result.append(tok.raw)
            continue

        # Try whole-token match first
        whole = ASCIIPA_TO_IPA_MAP.get(tok.raw)
        if whole is not None:
            result.append(whole)
            continue

        # Decompose: convert base, then each modifier
        base_ipa = ASCIIPA_TO_IPA_MAP.get(tok.base, tok.base)
        parts = [base_ipa]
        for mod in tok.modifiers:
            mod_ipa = ASCIIPA_TO_IPA_MAP.get(mod, "")
            if mod_ipa:
                parts.append(mod_ipa)
        result.append("".join(parts))
    return "".join(result)
