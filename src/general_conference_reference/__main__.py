# Copyright (c) Meta Platforms, Inc. and affiliates.
# Copyright (c) WhatsApp LLC
#
# This source code is licensed under the MIT license found in the
# LICENSE.md file in the root directory of this source tree.

"""Command-line interface for reference material from General Conference."""

import asyncio
import logging
from pathlib import Path

import click

from .gcon import (
    GeneralConference,
    PipelineConfig,
    STEP0_FETCH_TALK_LIST,
    STEP9_WRITE_REFERENCE_DOCX,
)


@click.command()
@click.argument("output_path", type=click.Path(path_type=Path))
@click.option("--year", type=str, default="2026")
@click.option("--month", type=str, default="04")
@click.option("--language", type=str, default="eng")
@click.option(
    "--until-step",
    type=click.IntRange(STEP0_FETCH_TALK_LIST, STEP9_WRITE_REFERENCE_DOCX),
    default=STEP9_WRITE_REFERENCE_DOCX,
    show_default=True,
)
@click.option("--concurrency", type=click.IntRange(1, None), default=4, show_default=True)
@click.option("--force/--no-force", default=False, show_default=True)
@click.option("--outline-model", type=str, default="gpt-5.5", show_default=True)
@click.option("--themes-model", type=str, default="gpt-5.5", show_default=True)
@click.option("--key-principles-model", type=str, default="gpt-5.5", show_default=True)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="INFO",
    show_default=True,
)
def main(
    output_path: Path,
    year: str,
    month: str,
    language: str,
    until_step: int,
    concurrency: int,
    force: bool,
    outline_model: str,
    themes_model: str,
    key_principles_model: str,
    log_level: str,
) -> None:
    """Generate General Conference reference material."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    general_conference = GeneralConference(
        output_path=output_path,
        year=year,
        month=month,
        language=language,
        config=PipelineConfig(
            outline_model=outline_model,
            themes_model=themes_model,
            key_principles_model=key_principles_model,
            run_until_step=until_step,
            concurrency=concurrency,
            force=force,
        ),
    )
    asyncio.run(general_conference.execute())
    logging.getLogger(__name__).info(
        "Completed conference pipeline for %s-%s in %s",
        year,
        month,
        general_conference.root_dir,
    )


if __name__ == "__main__":
    main()  # type: ignore
