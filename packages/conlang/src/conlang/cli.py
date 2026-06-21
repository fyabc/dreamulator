"""CLI entry point for the standalone conlang tool."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="conlang",
    help="Conlang toolkit: ASCIIPA encoding, SCA sound change, morphology, and lexicon.",
    no_args_is_help=True,
)

# Sub-command groups
sca_app = typer.Typer(help="Sound Change Applier (SCA) tools.")
asciipa_app = typer.Typer(help="ASCIIPA encoding/decoding tools.")
app.add_typer(sca_app, name="sca")
app.add_typer(asciipa_app, name="asciipa")


@app.command()
def version() -> None:
    """Show conlang version."""
    from conlang import __version__

    typer.echo(f"conlang v{__version__}")


@asciipa_app.command()
def encode(
    ipa: str = typer.Argument(help="IPA string to encode as ASCIIPA"),
) -> None:
    """Convert IPA notation to ASCIIPA."""
    from conlang.phonology.asciipa import ipa_to_asciipa

    result = ipa_to_asciipa(ipa)
    typer.echo(result)


@asciipa_app.command()
def decode(
    asciipa: str = typer.Argument(help="ASCIIPA string to decode to IPA"),
) -> None:
    """Convert ASCIIPA notation to IPA."""
    from conlang.phonology.asciipa import asciipa_to_ipa

    result = asciipa_to_ipa(asciipa)
    typer.echo(result)


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
        help="Input format: asciipa, ipa, or xsampa",
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
    """Synthesize and play a phonetic string.

    Default input format is ASCIIPA. Use --format to specify IPA or X-SAMPA.

    Examples:

      conlang speak "p^h a . t a"

      conlang speak "θɪŋk" --format ipa

      conlang speak "p_h a t a" --format xsampa -o out.wav

      conlang speak "!a:55" --language zu
    """
    from conlang.phonology.xsampa import speak as tts_speak

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
