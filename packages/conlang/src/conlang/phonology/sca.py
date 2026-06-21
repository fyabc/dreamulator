"""SCA (Sound Change Applier) engine — token-aware sound change simulator.

The SCA engine applies ordered phonological rules to a lexicon,
simulating historical sound change. Unlike naive string-replacement
approaches, this engine first tokenizes ASCIIPA strings into indivisible
Token objects, ensuring rules never accidentally modify sub-components
of multi-character constructs like ``{sh}`` or ``p^h``.

Rule syntax::

    TARGET > OUTPUT / LEFT_ENV _ RIGHT_ENV [PROBABILITY]

Examples::

    p > f / V _ V              # Lenition: p → f between vowels
    t > t^h / # _              # Aspiration at word onset
    :55 > :5 / _               # Tone merger
    k > {ch} / _ Front [0.4]   # Probabilistic palatalization

Environment tokens:
    _   Target position (required in env specification)
    #   Word boundary
    V   Category reference (all vowels)
    C   Category reference (all consonants)
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from conlang.phonology.asciipa import ASCIIPATokenizer, Token


@dataclass
class Rule:
    """A single sound change rule.

    Attributes:
        target: Token string to match for replacement.
        output: Replacement token string.
        left_env: Required left environment (None = any, '#' = word start).
        right_env: Required right environment (None = any, '#' = word end).
        probability: Application probability (1.0 = always, 0.3 = 30% per gen).
        raw: Original rule string (for debugging).
    """

    target: str
    output: str
    left_env: str | None = None
    right_env: str | None = None
    probability: float = 1.0
    raw: str = ""


@dataclass
class Category:
    """A named set of phonemes used in rule environments.

    Attributes:
        name: Category name (e.g. 'V', 'C', 'Front').
        members: Set of ASCIIPA token strings in this category.
    """

    name: str
    members: set[str] = field(default_factory=set)


class SCAEngine:
    """Token-aware Sound Change Applier engine.

    Usage::

        engine = SCAEngine()
        engine.add_category("V", ["i", "e", "a", "o", "u"])
        engine.add_rule("p > f / V _ V")
        engine.add_rule("t > s / V _ V")

        result = engine.apply("t a p a")
        # → "t a f a" (only medial p changes)
    """

    def __init__(self, *, seed: int | None = None) -> None:
        self._tokenizer = ASCIIPATokenizer()
        self._categories: dict[str, Category] = {}
        self._rules: list[Rule] = []
        self._lexicon: dict[str, list[Token]] = {}
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Category management
    # ------------------------------------------------------------------

    def add_category(self, name: str, members: list[str] | str) -> None:
        """Define a phoneme category.

        Args:
            name: Category name (e.g. 'V', 'Click').
            members: List of token strings, or space-separated string.
        """
        if isinstance(members, str):
            members = members.split()
        self._categories[name] = Category(name=name, members=set(members))

    def add_categories(self, categories: dict[str, list[str] | str]) -> None:
        """Add multiple categories at once.

        Args:
            categories: Dict of name → members.
        """
        for name, members in categories.items():
            self.add_category(name, members)

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule_str: str) -> None:
        """Parse and add a sound change rule.

        Args:
            rule_str: Rule in format ``TARGET > OUTPUT / LEFT _ RIGHT [PROB]``.
        """
        rule = self._parse_rule(rule_str)
        self._rules.append(rule)

    def add_rules(self, rules: list[str]) -> None:
        """Add multiple rules at once.

        Args:
            rules: List of rule strings.
        """
        for r in rules:
            self.add_rule(r)

    def clear_rules(self) -> None:
        """Remove all rules."""
        self._rules.clear()

    # ------------------------------------------------------------------
    # Lexicon management
    # ------------------------------------------------------------------

    def load_lexicon(self, words: list[str] | dict[str, float]) -> None:
        """Load a lexicon for batch processing.

        Args:
            words: List of ASCIIPA words, or dict of word → frequency.
        """
        self._lexicon.clear()
        if isinstance(words, dict):
            for word in words:
                self._lexicon[word] = self._tokenizer.tokenize(word)
        else:
            for word in words:
                self._lexicon[word] = self._tokenizer.tokenize(word)

    def load_lexicon_file(self, path: str | Path) -> None:
        """Load a lexicon from a YAML file.

        Expected format::

            entries:
              - word: "|a:55"
                gloss: "spirit"
                frequency: 0.95
              - word: "p'a"
                gloss: "guard"
                frequency: 0.80

        Or simple list format::

            - "|a:55"
            - "p'a"

        Args:
            path: Path to YAML file.
        """
        import yaml

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if isinstance(data, list):
            words = []
            for item in data:
                if isinstance(item, dict):
                    words.append(item["word"])
                else:
                    words.append(str(item))
            self.load_lexicon(words)
        elif isinstance(data, dict) and "entries" in data:
            words = [entry["word"] for entry in data["entries"]]
            self.load_lexicon(words)
        else:
            raise ValueError(f"Unexpected lexicon format in {path}")

    def load_rules_file(self, path: str | Path) -> None:
        """Load SCA rules from a .sca text file.

        Lines starting with ``//`` or ``#`` are comments.
        Category definitions use ``NAME = member1 member2 ...``.
        Rules use ``TARGET > OUTPUT / ENV``.

        Args:
            path: Path to .sca file.
        """
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith("//") or line.startswith("#"):
                    continue
                # Category definition: NAME = member1 member2 ...
                if "=" in line and ">" not in line:
                    name, _, members = line.partition("=")
                    name = name.strip()
                    members = members.strip()
                    self.add_category(name, members.split())
                else:
                    self.add_rule(line)

    # ------------------------------------------------------------------
    # Core: apply rules
    # ------------------------------------------------------------------

    def apply(self, word: str) -> str:
        """Apply all rules to a single word (deterministic, one pass).

        Args:
            word: ASCIIPA word string.

        Returns:
            Evolved ASCIIPA word string.
        """
        tokens = self._tokenizer.tokenize(word)
        for rule in self._rules:
            tokens = self._apply_rule_to_tokens(tokens, rule)
        return self._join_tokens(tokens)

    def apply_with_frequency(
        self, word: str, frequency: float = 1.0
    ) -> str:
        """Apply rules probabilistically based on word frequency.

        Args:
            word: ASCIIPA word string.
            frequency: Word usage frequency (0.0–1.0). Higher = more likely to change.

        Returns:
            Evolved ASCIIPA word string.
        """
        tokens = self._tokenizer.tokenize(word)
        for rule in self._rules:
            tokens = self._apply_rule_to_tokens(tokens, rule, frequency=frequency)
        return self._join_tokens(tokens)

    def apply_all(self) -> dict[str, str]:
        """Apply rules to all loaded lexicon entries.

        Returns:
            Dict of original_word → evolved_word.
        """
        results: dict[str, str] = {}
        for word, tokens in self._lexicon.items():
            evolved_tokens = tokens[:]
            for rule in self._rules:
                evolved_tokens = self._apply_rule_to_tokens(evolved_tokens, rule)
            results[word] = self._join_tokens(evolved_tokens)
        return results

    def simulate_generations(
        self,
        generations: int = 5,
        *,
        frequencies: dict[str, float] | None = None,
    ) -> dict[str, list[str]]:
        """Simulate sound change across multiple generations.

        Args:
            generations: Number of generations to simulate.
            frequencies: Optional dict of word → frequency.

        Returns:
            Dict of original_word → list of forms at each generation.
        """
        if frequencies is None:
            frequencies = {w: 1.0 for w in self._lexicon}

        history: dict[str, list[str]] = {}
        current_tokens: dict[str, list[Token]] = {
            w: toks[:] for w, toks in self._lexicon.items()
        }

        for word in self._lexicon:
            history[word] = [self._join_tokens(current_tokens[word])]

        for _gen in range(generations):
            for word in self._lexicon:
                freq = frequencies.get(word, 1.0)
                toks = current_tokens[word]
                for rule in self._rules:
                    toks = self._apply_rule_to_tokens(toks, rule, frequency=freq)
                current_tokens[word] = toks
                history[word].append(self._join_tokens(toks))

        return history

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_rule(self, rule_str: str) -> Rule:
        """Parse a rule string into a Rule object."""
        raw = rule_str
        probability = 1.0

        # Extract probability tag [0.X]
        prob_match = re.search(r"\[([0-9.]+)\]", rule_str)
        if prob_match:
            probability = float(prob_match.group(1))
            rule_str = rule_str[: prob_match.start()].strip()

        # Split on ' > ' (with spaces) to separate target from the rest.
        # This avoids matching > inside tokens like t> or d>.
        if " > " not in rule_str:
            raise ValueError(f"Invalid rule (missing ' > '): {raw}")

        target, rest = rule_str.split(" > ", 1)
        target = target.strip()

        # Split on ' / ' (with spaces) to separate output from environment.
        if " / " in rest:
            output, env_str = rest.split(" / ", 1)
        else:
            output = rest
            env_str = ""

        output = output.strip()
        env_str = env_str.strip()

        # Parse environment: LEFT _ RIGHT
        # The underscore here is the TARGET POSITION marker, distinct from
        # the underscore used in ASCIIPA subscript modifiers (e.g. _o, _v).
        # Since we already split on ' / ', the env_str is isolated.
        left_env: str | None = None
        right_env: str | None = None
        if env_str:
            parts = env_str.split("_", 1)
            left_env = parts[0].strip() or None
            right_env = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

        return Rule(
            target=target,
            output=output,
            left_env=left_env,
            right_env=right_env,
            probability=probability,
            raw=raw,
        )

    def _apply_rule_to_tokens(
        self,
        tokens: list[Token],
        rule: Rule,
        *,
        frequency: float = 1.0,
    ) -> list[Token]:
        """Apply a single rule to a list of tokens."""
        output_tokens = self._tokenizer.tokenize(rule.output) if rule.output else []
        result: list[Token] = []

        for i, tok in enumerate(tokens):
            if self._token_matches(tok, rule.target):
                # Check environment
                left_ok = self._check_env(
                    tokens, i - 1, rule.left_env, is_boundary=(i == 0)
                )
                right_ok = self._check_env(
                    tokens, i + 1, rule.right_env, is_boundary=(i == len(tokens) - 1)
                )

                if left_ok and right_ok:
                    # Check probability
                    actual_prob = rule.probability * frequency
                    if actual_prob >= 1.0 or self._rng.random() < actual_prob:
                        result.extend(output_tokens)
                        continue

            result.append(tok)
        return result

    def _token_matches(self, token: Token, pattern: str) -> bool:
        """Check if a token matches a target pattern."""
        # Exact match
        if token.raw == pattern:
            return True
        # Category match
        cat = self._categories.get(pattern)
        if cat and token.raw in cat.members:
            return True
        # Base character match (for simple single-char targets)
        return len(pattern) == 1 and token.base == pattern

    def _check_env(
        self,
        tokens: list[Token],
        index: int,
        env: str | None,
        *,
        is_boundary: bool,
    ) -> bool:
        """Check if the environment constraint is satisfied."""
        if env is None:
            return True
        if env == "#":
            return is_boundary
        if is_boundary:
            return False
        if 0 <= index < len(tokens):
            return self._token_matches(tokens[index], env)
        return False

    @staticmethod
    def _join_tokens(tokens: list[Token]) -> str:
        """Join tokens back into an ASCIIPA string."""
        return " ".join(tok.raw for tok in tokens)
