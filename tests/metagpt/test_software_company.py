#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2023/5/15 11:40
@Author  : alexanderwu
@File    : test_software_company.py
"""
import pytest
from typer.testing import CliRunner

from metagpt.core.logs import logger
from metagpt.software_company import app
from metagpt.team import Team

runner = CliRunner()


@pytest.mark.asyncio
async def test_empty_team(new_filename):
    # FIXME: we're now using "metagpt" cli, so the entrance should be replaced instead.
    company = Team()
    history = await company.run(idea="Build a simple search system. I will upload my files later.")
    logger.info(history)


def test_software_company(new_filename):
    args = ["Make a cli snake game"]
    result = runner.invoke(app, args)
    logger.info(result)
    logger.info(result.output)


def test_software_company_with_run_tests():
    args = ["Make a cli snake game", "--run-tests", "--n-round=8"]
    result = runner.invoke(app, args)
    logger.info(result.output)
    # assert "unittest" in result.output.lower() or "pytest" in result.output.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-s"])
