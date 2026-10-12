# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest
from pydantic import ValidationError

from veyra.telephony.numbering import NumberingPlan


def test_defaults_describe_a_usable_plan():
    plan = NumberingPlan()
    assert plan.problems() == []
    assert plan.extension_length == 4 and plan.reserved_prefixes == ["0", "9", "911", "933"]
    assert "4-digit numbers from 1000 to 7999" in plan.describe()
    assert plan.check_number("1001") == []
    assert plan.next_available([]) == "1000"
    assert plan.next_available(["1000", "1001"]) == "1002"
    assert plan.next_available(["1000"], after="1500") == "1501"


def test_check_number_explains_every_rule():
    plan = NumberingPlan()
    assert plan.check_number("12a4") == ["Extension numbers contain digits only."]
    assert plan.check_number("100") == ["Extension numbers have 4 digits."]
    assert plan.check_number("8000") == ["Extensions are numbered from 1000 to 7999."]
    assert plan.check_number("0100") == [
        "Extensions are numbered from 1000 to 7999.",
        "Numbers starting with 0 are reserved.",
    ]
    wide = NumberingPlan(
        first_extension="0000", last_extension="9999", reserved_prefixes=["0", "911", "933"]
    )
    assert wide.check_number("9110") == ["Numbers starting with 911 are reserved."]
    assert wide.check_number("9330") == ["Numbers starting with 933 are reserved."]
    assert wide.check_number("0911") == ["Numbers starting with 0 are reserved."]
    assert wide.check_number("1911") == [] and wide.check_number("9000") == []
    assert wide.next_available([]) == "1000"  # 0xxx is reserved


def test_reserved_prefix_skipping_and_exhaustion():
    plan = NumberingPlan(
        extension_length=3, first_extension="100", last_extension="103", reserved_prefixes=["10"]
    )
    assert plan.problems() == ["Every number in the range starts with a reserved prefix."]
    plan = NumberingPlan(
        extension_length=3, first_extension="100", last_extension="102", reserved_prefixes=[]
    )
    assert plan.next_available(["100", "101", "102"]) is None
    assert plan.next_available(["100"]) == "101"


def test_plan_validation():
    assert NumberingPlan(
        extension_length=3, first_extension="1000", last_extension="1999"
    ).problems() == [
        "The first extension 1000 does not have 3 digits.",
        "The last extension 1999 does not have 3 digits.",
    ]
    assert NumberingPlan(first_extension="2000", last_extension="1999").problems() == [
        "The last extension must not be lower than the first."
    ]
    with pytest.raises(ValidationError):
        NumberingPlan(first_extension="10a0")
    with pytest.raises(ValidationError):
        NumberingPlan(extension_length=2)
    with pytest.raises(ValidationError):
        NumberingPlan(reserved_prefixes=["9x"])
    # prefixes are trimmed, deduplicated and empties dropped
    assert NumberingPlan(reserved_prefixes=[" 9", "9", "", "0"]).reserved_prefixes == ["9", "0"]
