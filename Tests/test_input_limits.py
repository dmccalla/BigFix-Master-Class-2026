# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Typed values are checked against explicit patterns and ceilings.

str.isdigit() and int() accept non-ASCII digits, so a typed value such as a
superscript two used to pass the check and then crash the conversion. Names
that become folder and file names are also capped.
"""

from __future__ import annotations

import pytest
import run_diagnostics as engine

from Lib.Core.input_utils import (
    MAX_NAME_CHARS,
    name_length_warning,
    parse_whole_number,
    positive_ascii_int_or_blank,
)

NON_ASCII_DIGITS = ["\u00b2", "\u0663", "\uff12", "1\u00b2"]


@pytest.mark.parametrize("value", ["8", " 16 ", 8, 8.0, "-1", "0"])
def test_parse_whole_number_accepts_plain_numbers(value) -> None:
    assert isinstance(parse_whole_number(value, "Processors"), int)


@pytest.mark.parametrize(
    "value",
    ["", "abc", "1e3", "8.5", "0x10", "1" * 10, True, None, *NON_ASCII_DIGITS],
)
def test_parse_whole_number_rejects_everything_else(value) -> None:
    with pytest.raises(ValueError, match="Processors"):
        parse_whole_number(value, "Processors")


@pytest.mark.parametrize("value", ["8", " 16 ", "999999999"])
def test_positive_ascii_int_or_blank_keeps_valid_values(value) -> None:
    assert positive_ascii_int_or_blank(value) == value.strip()


@pytest.mark.parametrize(
    "value", ["", "0", "-1", "8.5", "1" * 10, None, "detecting...", *NON_ASCII_DIGITS]
)
def test_positive_ascii_int_or_blank_blanks_everything_else(value) -> None:
    assert positive_ascii_int_or_blank(value) == ""


def _perfmon_field(key: str):
    module = engine.MODULE_BY_KEY["perfmon"]
    return module, next(f for f in module.inputs_schema if f.key == key)


@pytest.mark.parametrize("raw", ["5000", "99999999", "\u00b2"])
def test_engine_rejects_detected_counts_over_the_ceiling_or_malformed(raw) -> None:
    module, field = _perfmon_field("logical_processors")
    with pytest.raises(ValueError):
        engine._resolve_input_value_from_config(module, field, raw, {}, None)


def test_engine_accepts_a_normal_detected_count() -> None:
    module, field = _perfmon_field("logical_processors")
    value, _cache = engine._resolve_input_value_from_config(module, field, "64", {}, None)
    assert value == 64


HOSTILE_NAMES = ["..\\..\\x", 'a/b:c*?"<>|', "x" * 5000, "\u00b2" * 100]


@pytest.mark.parametrize("hostile", HOSTILE_NAMES)
def test_name_helper_is_filesystem_safe_and_bounded(hostile: str) -> None:
    clean = engine.sanitize_run_name(hostile)
    assert 0 < len(clean) <= MAX_NAME_CHARS
    assert all(ch.isalnum() or ch == "_" for ch in clean)


def test_name_length_warning_fires_only_over_the_limit() -> None:
    assert name_length_warning("", "Run name") == ""
    assert name_length_warning("x" * MAX_NAME_CHARS, "Run name") == ""
    message = name_length_warning("x" * (MAX_NAME_CHARS + 1), "Run name")
    assert message.startswith("Run name is longer than")
    assert str(MAX_NAME_CHARS) in message


def test_name_length_warning_measures_the_folder_form() -> None:
    assert name_length_warning("a" + "!" * 200 + "b", "Run name") == ""
