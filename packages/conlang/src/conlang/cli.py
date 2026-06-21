"""CLI entry point for the standalone conlang tool."""

from __future__ import annotations

import logging

import typer

app = typer.Typer(
    name="conlang",
    help="Conlang toolkit: ASCIIPA encoding, SCA sound change, morphology, and lexicon.",
    no_args_is_help=True,
)

# Sub-command groups
sca_app = typer.Typer(help="Sound Change Applier (SCA) tools.")
app.add_typer(sca_app, name="sca")


@app.callback()
def main(
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Enable debug logging.",
    ),
) -> None:
    """Global options applied to all subcommands."""
    from conlang.utils.logging import setup_logging

    level = logging.DEBUG if verbose else logging.INFO
    setup_logging(level)


@app.command()
def version() -> None:
    """Show conlang version."""
    from conlang import __version__

    typer.echo(f"conlang v{__version__}")


@app.command()
def convert(
    text: str = typer.Argument(help="Phonetic string to convert"),
    from_fmt: str = typer.Option(
        "asciipa", "--from", "-f",
        help="Input format: asciipa, ipa",
    ),
    to_fmt: str = typer.Option(
        "ipa", "--to", "-t",
        help="Output format: asciipa, ipa, xsampa, kirshenbaum",
    ),
    chars: bool = typer.Option(
        False, "--chars", "-c",
        help="Show each character's Unicode name and codepoint",
    ),
    check: bool = typer.Option(
        False, "--check",
        help="Validate that all input characters are recognized IPA",
    ),
) -> None:
    """Convert between phonetic notations.

    All conversions go through Unicode IPA as the universal intermediate.

    Examples:

      conlang convert "{th}I{ng}k" -t ipa

      conlang convert "həlˈoʊ" -f ipa -t asciipa

      conlang convert "həlˈəʊ" -f ipa -t kirshenbaum

      conlang convert "həlˈəʊ" -f ipa --chars

      conlang convert "həlˈəʊ" -f ipa --check
    """
    # Step 1: Convert input to Unicode IPA
    from conlang.phonology.asciipa import asciipa_to_ipa, ipa_to_asciipa

    fmt = from_fmt.lower().strip()
    if fmt == "asciipa":
        ipa = asciipa_to_ipa(text)
    elif fmt == "ipa":
        ipa = text
    else:
        typer.echo(f"Error: unknown input format '{from_fmt}'", err=True)
        raise typer.Exit(code=1)

    # Step 2: Check (validate)
    if check:
        from conlang.phonology.charinfo import validate_ipa

        valid, invalid = validate_ipa(ipa)
        if valid:
            typer.echo("Valid: all characters are recognized IPA symbols")
        else:
            unique = sorted(set(invalid))
            chars_str = " ".join(f"'{c}' (U+{ord(c):04X})" for c in unique)
            typer.echo(f"Invalid: {len(unique)} unrecognized character(s): {chars_str}")
        return

    # Step 3: Chars (describe each character)
    if chars:
        from conlang.phonology.charinfo import describe_string

        for ch, hex_code, desc, _uni_name in describe_string(ipa):
            typer.echo(f"'{ch}'\t{hex_code}\t{desc}")
        return

    # Step 4: Convert IPA to target format
    target = to_fmt.lower().strip()
    if target == "ipa":
        typer.echo(ipa)
    elif target == "asciipa":
        typer.echo(ipa_to_asciipa(ipa))
    elif target == "xsampa":
        from conlang.phonology.xsampa import ipa_to_xsampa

        typer.echo(ipa_to_xsampa(ipa))
    elif target == "kirshenbaum":
        from conlang.phonology.espeak_ng import ipa_to_kirshenbaum

        typer.echo(ipa_to_kirshenbaum(ipa))
    else:
        typer.echo(f"Error: unknown output format '{to_fmt}'", err=True)
        raise typer.Exit(code=1)


@sca_app.command()
def run(
    rules: str = typer.Option(..., help="Path to SCA rules file (.sca)"),
    lexicon: str = typer.Option(..., help="Path to lexicon file (.yaml)"),
    output: str | None = typer.Option(None, help="Output file path (stdout if omitted)"),
) -> None:
    """Run sound change rules on a lexicon."""
    from conlang.phonology.sca import SCAEngine

    engine = SCAEngine()
    engine.load_rules_file(rules)
    engine.load_lexicon_file(lexicon)
    results = engine.apply_all()

    lines = [f"{proto} → {modern}" for proto, modern in results.items()]
    text = "\n".join(lines)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        typer.echo(f"Written {len(results)} entries to {output}")
    else:
        typer.echo(text)


@sca_app.command()
def tokenize(
    word: str = typer.Argument(help="ASCIIPA word to tokenize"),
) -> None:
    """Show the token breakdown of an ASCIIPA word."""
    from conlang.phonology.asciipa import ASCIIPATokenizer

    tokenizer = ASCIIPATokenizer()
    tokens = tokenizer.tokenize(word)
    for tok in tokens:
        typer.echo(f"  {tok!r}")


@app.command()
def speak(
    text: str = typer.Argument(help="Phonetic string to speak"),
    fmt: str = typer.Option(
        "asciipa", "--format", "-f",
        help="Input format: asciipa, ipa, or kirshenbaum",
    ),
    output: str | None = typer.Option(
        None, "--output", "-o",
        help="Save .wav to this path (omit to play only)",
    ),
    play: bool = typer.Option(
        True, "--play/--no-play",
        help="Play audio after synthesis",
    ),
    language: str = typer.Option(
        "en", "--language", "-l",
        help="eSpeak language code (e.g. 'zu' for clicks)",
    ),
    speed: int = typer.Option(
        130, "--speed", "-s",
        help="Speech speed (words per minute)",
    ),
    pitch: int = typer.Option(
        50, "--pitch", "-p",
        help="Pitch (0–99)",
    ),
) -> None:
    """Synthesize and play a phonetic string via eSpeak-NG (Kirshenbaum format).

    Default input format is ASCIIPA. Use --format to specify IPA or Kirshenbaum.

    Examples:

      conlang speak "p^h a . t a"

      conlang speak "həlˈoʊ" --format ipa

      conlang speak "h @ l ' o U" -f kirshenbaum -o out.wav

      conlang speak "!a:55" --language zu
    """
    from conlang.phonology.espeak_ng import speak as tts_speak

    if output is None and not play:
        typer.echo("Error: specify --output or --play (or both).", err=True)
        raise typer.Exit(code=1)

    try:
        wav = tts_speak(
            text,
            input_format=fmt,
            output=output,
            play=play,
            language=language,
            speed=speed,
            pitch=pitch,
        )
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    if wav and output:
        typer.echo(f"Saved: {wav}")
