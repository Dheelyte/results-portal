"""Rendering the report card (ARCHITECTURE.md §9).

Jinja2 → WeasyPrint → A4 portrait. The template does the layout; this module
does the three things around it that need stating.

**The filters.** A card prints a number the way a person writes it — 40, not
40.00 — and prints nothing at all where there is no figure. §9 is explicit
that an empty column is never zero-filled, so `number` and `blank` both
return an empty string for `None` rather than a placeholder.

**Determinism.** §9: "same data renders byte-identically, so regeneration is
verifiable." Two things would otherwise break that, and both are handled:
WeasyPrint stamps a creation date into every PDF, and it embeds its own
version. Both are pinned below. The fonts are pinned in the image
(`api/Dockerfile`) for the same reason.

**No arithmetic.** Every figure arrives decided. A filter that rounded, or a
template that summed a column, would be a second implementation of a rule
living outside `services/` (CLAUDE.md rule 2).
"""

import datetime as dt
import decimal
import functools
import logging
import os
import pathlib
from typing import Any

import jinja2
import markupsafe

logger = logging.getLogger(__name__)

TEMPLATES = pathlib.Path(__file__).parent / "templates"

# §9: "Deterministic output: same data renders byte-identically, so
# regeneration is verifiable."
#
# Getting that took finding out why it was not true. WeasyPrint subsets the
# fonts it embeds, fontTools writes the subset's `head.modified` timestamp
# from the clock, and two renders a second apart therefore differ — inside a
# compressed stream, so the difference looks like a compression artefact and
# is not one. Neither `uncompressed_pdf` nor a fixed PYTHONHASHSEED helps;
# `full_fonts=True` does, by embedding the whole face, and takes a 20 KB card
# to 420 KB — past §9's own 300 KB budget.
#
# `SOURCE_DATE_EPOCH` is the reproducible-builds convention and fontTools
# honours it. Set here rather than in the Dockerfile so it holds wherever the
# code runs — CI, a developer's machine, a one-off script — and with
# `setdefault`, so an operator who has set it for their own build keeps their
# value (docs/DECISIONS.md D85).
#
# The real moment a card was produced is on `term_reports.pdf_generated_at`
# and in the audit log, which are where anyone would look for it.
REPRODUCIBLE_EPOCH = "946684800"  # 2000-01-01T00:00:00Z


def number(value: object) -> str:
    """A figure as the card prints it: 40, not 40.00; nothing for nothing."""
    if value is None or value == "":
        return ""
    if isinstance(value, decimal.Decimal):
        return f"{value.normalize():f}"
    return str(value)


def blank(value: object) -> str:
    """Whatever it is, or an empty string — never "None" on a parent's card."""
    return "" if value is None else str(value)


def as_date(value: dt.date | None) -> str:
    """ISO, because a card crossing a date line should not be ambiguous."""
    return "" if value is None else value.isoformat()


@functools.cache
def environment() -> jinja2.Environment:
    """The template environment, built once.

    `autoescape` is on: a narrative passage is free text a teacher typed, and
    an ampersand in "Art & Music" should not be able to break the document —
    let alone anything worse pasted from elsewhere.
    """
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["number"] = number
    env.filters["blank"] = blank
    env.filters["date"] = as_date
    return env


def render_html(card: Any) -> str:
    """The card as HTML. Separated from the PDF step so it can be inspected.

    Worth having on its own: an HTML diff is readable in a review, and a
    failing golden-file test is far easier to understand from the markup than
    from extracted PDF text.

    The stylesheet is wrapped in `Markup` because autoescaping is on, and it
    must be: a narrative passage is free text a teacher typed. Without the
    wrapper the quotes in `font-family: "DejaVu Sans"` arrive as `&#34;`, the
    rule fails to parse, and **the whole stylesheet is silently dropped** —
    the card still renders, in a default font, at a default size, which is
    exactly the kind of failure that gets noticed by a school rather than by
    a test (docs/DECISIONS.md D84).
    """
    stylesheet = markupsafe.Markup((TEMPLATES / "card.css").read_text(encoding="utf-8"))
    return environment().get_template("card.html").render(card=card, stylesheet=stylesheet)


def render_pdf(card: Any) -> bytes:
    """The card as an A4 PDF.

    WeasyPrint is imported here rather than at module load: it pulls in Pango
    and HarfBuzz through cffi, which costs real time at import, and nothing
    outside this function needs it.
    """
    os.environ.setdefault("SOURCE_DATE_EPOCH", REPRODUCIBLE_EPOCH)

    from weasyprint import HTML

    return HTML(string=render_html(card)).write_pdf()
