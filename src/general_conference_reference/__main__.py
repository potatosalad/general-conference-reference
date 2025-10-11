# Copyright (c) Meta Platforms, Inc. and affiliates.
# Copyright (c) WhatsApp LLC
#
# This source code is licensed under the MIT license found in the
# LICENSE.md file in the root directory of this source tree.

"""Command-line interface for reference material from General Conference."""
import asyncio
import click
import json
import pprint

from . import GeneralConference


@click.command()
@click.argument("output_path", type=click.Path())
@click.option("--year", type=str, default="2025")
@click.option("--month", type=str, default="10")
@click.option("--language", type=str, default="eng")
def main(output_path: str, year: str, month: str, language: str):
    """Command-line utility for codegen and schema validation."""
    general_conference: GeneralConference = GeneralConference(output_path=output_path, year=year, month=month, language=language)
    asyncio.run(general_conference.execute())
    pprint.pprint(general_conference)


if __name__ == "__main__":
    main()  # type: ignore
