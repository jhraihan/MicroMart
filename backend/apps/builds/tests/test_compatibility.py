"""
The PC-builder compatibility rules.

These test `services/compatibility.py` directly rather than through the API,
because the module is deliberately pure: it takes a selection of profiles and
returns a report, touching no database. That makes every rule testable as a
plain function call, and it is the reason the rules live apart from the
persistence layer at all.

What each test pins is the *level* as much as the outcome. The three-way split
between `error` (two known values conflict), `warning` (a real risk) and
`info` (a check could not run) is the design: flattening them would either cry
wolf on a missing spec or hide a genuine conflict, and a test that only
asserted "something was reported" would let that regression through.
"""
import pytest

from apps.builds.services import compatibility
from apps.catalog.models import ComponentProfile, ComponentSlot


def profile(slot, **fields):
    """
    An unsaved ComponentProfile.

    Unsaved on purpose: the rules read attributes and never touch the
    database, so giving them a saved row would buy nothing and make a pure
    unit test need a transaction.
    """
    return ComponentProfile(slot=slot, **fields)


def entry(prof, name="Part", quantity=1):
    return {"profile": prof, "name": name, "quantity": quantity}


def codes(report, level=None):
    return {
        f.code for f in report.findings if level is None or f.level == level
    }


# ---------------------------------------------------------------------------
# Socket
# ---------------------------------------------------------------------------
def test_a_cpu_and_board_with_different_sockets_is_an_error():
    report = compatibility.evaluate(
        {
            ComponentSlot.CPU: entry(profile(ComponentSlot.CPU, socket="AM4")),
            ComponentSlot.MOTHERBOARD: entry(
                profile(ComponentSlot.MOTHERBOARD, socket="AM5")
            ),
        }
    )
    assert "SOCKET_MISMATCH" in codes(report, "error")
    assert report.is_compatible is False


def test_socket_comparison_ignores_case_spacing_and_hyphens():
    """
    "LGA 1700", "lga1700" and "LGA-1700" name one socket.

    Spelling varies across manufacturers and across our own seed data, and a
    rule that rejected a build over a hyphen would be worse than no rule.
    """
    report = compatibility.evaluate(
        {
            ComponentSlot.CPU: entry(profile(ComponentSlot.CPU, socket="LGA 1700")),
            ComponentSlot.MOTHERBOARD: entry(
                profile(ComponentSlot.MOTHERBOARD, socket="lga-1700")
            ),
        }
    )
    assert "SOCKET_MISMATCH" not in codes(report)


def test_an_unknown_socket_is_reported_as_unchecked_not_as_a_conflict():
    report = compatibility.evaluate(
        {
            ComponentSlot.CPU: entry(profile(ComponentSlot.CPU, socket="")),
            ComponentSlot.MOTHERBOARD: entry(
                profile(ComponentSlot.MOTHERBOARD, socket="AM5")
            ),
        }
    )
    assert "SOCKET_UNKNOWN" in codes(report, "info")
    # Missing data must never fail a build: the shopper cannot fix a gap in
    # our own specifications.
    assert report.is_compatible is True


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
def test_ddr4_memory_in_a_ddr5_board_is_an_error():
    report = compatibility.evaluate(
        {
            ComponentSlot.RAM: entry(profile(ComponentSlot.RAM, ram_type="DDR4")),
            ComponentSlot.MOTHERBOARD: entry(
                profile(ComponentSlot.MOTHERBOARD, ram_type="DDR5")
            ),
        }
    )
    assert "RAM_TYPE_MISMATCH" in codes(report, "error")


def test_more_modules_than_the_board_has_slots_is_an_error():
    report = compatibility.evaluate(
        {
            ComponentSlot.RAM: entry(
                profile(ComponentSlot.RAM, ram_type="DDR4", module_count=2),
                quantity=2,  # two kits of two = four modules
            ),
            ComponentSlot.MOTHERBOARD: entry(
                profile(ComponentSlot.MOTHERBOARD, ram_type="DDR4", ram_slots=2)
            ),
        }
    )
    assert "RAM_SLOTS_EXCEEDED" in codes(report, "error")


def test_quantity_is_counted_against_the_boards_capacity_limit():
    """Two 64GB kits exceed a 64GB board, even though one kit would not."""
    report = compatibility.evaluate(
        {
            ComponentSlot.RAM: entry(
                profile(
                    ComponentSlot.RAM, ram_type="DDR4", capacity_gb=64, module_count=2
                ),
                quantity=2,
            ),
            ComponentSlot.MOTHERBOARD: entry(
                profile(
                    ComponentSlot.MOTHERBOARD,
                    ram_type="DDR4",
                    ram_slots=4,
                    max_ram_gb=64,
                )
            ),
        }
    )
    assert "RAM_CAPACITY_EXCEEDED" in codes(report, "error")


# ---------------------------------------------------------------------------
# Physical fit
# ---------------------------------------------------------------------------
def test_an_atx_board_in_a_case_that_takes_only_smaller_boards_is_an_error():
    report = compatibility.evaluate(
        {
            ComponentSlot.MOTHERBOARD: entry(
                profile(ComponentSlot.MOTHERBOARD, form_factor="ATX")
            ),
            ComponentSlot.CASE: entry(
                profile(
                    ComponentSlot.CASE,
                    supported_form_factors=["Micro-ATX", "Mini-ITX"],
                )
            ),
        }
    )
    assert "FORM_FACTOR_MISMATCH" in codes(report, "error")


def test_a_card_longer_than_the_case_allows_is_an_error():
    report = compatibility.evaluate(
        {
            ComponentSlot.GPU: entry(profile(ComponentSlot.GPU, length_mm=340)),
            ComponentSlot.CASE: entry(
                profile(ComponentSlot.CASE, max_gpu_length_mm=320)
            ),
        }
    )
    assert "GPU_TOO_LONG" in codes(report, "error")


def test_a_card_that_exactly_fills_the_case_is_allowed():
    """The limit is inclusive -- 320mm into a 320mm case fits."""
    report = compatibility.evaluate(
        {
            ComponentSlot.GPU: entry(profile(ComponentSlot.GPU, length_mm=320)),
            ComponentSlot.CASE: entry(
                profile(ComponentSlot.CASE, max_gpu_length_mm=320)
            ),
        }
    )
    assert "GPU_TOO_LONG" not in codes(report)


def test_a_cooler_taller_than_the_case_allows_is_an_error():
    report = compatibility.evaluate(
        {
            ComponentSlot.COOLER: entry(profile(ComponentSlot.COOLER, height_mm=170)),
            ComponentSlot.CASE: entry(
                profile(ComponentSlot.CASE, max_cooler_height_mm=160)
            ),
        }
    )
    assert "COOLER_TOO_TALL" in codes(report, "error")


# ---------------------------------------------------------------------------
# Cooling
# ---------------------------------------------------------------------------
def test_a_cooler_that_does_not_list_the_cpus_socket_is_an_error():
    report = compatibility.evaluate(
        {
            ComponentSlot.CPU: entry(profile(ComponentSlot.CPU, socket="AM5")),
            ComponentSlot.COOLER: entry(
                profile(ComponentSlot.COOLER, supported_sockets=["LGA1700", "AM4"])
            ),
        }
    )
    assert "COOLER_SOCKET_MISMATCH" in codes(report, "error")


def test_an_undersized_cooler_warns_rather_than_failing_the_build():
    """
    It will run, and it will throttle. That is a warning, not a refusal --
    plenty of people knowingly pair a modest cooler with a hot chip.
    """
    report = compatibility.evaluate(
        {
            ComponentSlot.CPU: entry(
                profile(ComponentSlot.CPU, socket="AM5", tdp_watts=120)
            ),
            ComponentSlot.COOLER: entry(
                profile(
                    ComponentSlot.COOLER,
                    supported_sockets=["AM5"],
                    cooler_max_tdp_watts=95,
                )
            ),
        }
    )
    assert "COOLER_UNDERSIZED" in codes(report, "warning")
    assert report.is_compatible is True


def test_a_hot_cpu_with_no_cooler_prompts_but_does_not_fail():
    report = compatibility.evaluate(
        {
            ComponentSlot.CPU: entry(
                profile(ComponentSlot.CPU, socket="LGA1700", tdp_watts=125)
            ),
        }
    )
    assert "COOLER_RECOMMENDED" in codes(report, "warning")
    assert report.is_compatible is True


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------
def test_a_psu_below_the_estimated_draw_is_an_error():
    report = compatibility.evaluate(
        {
            ComponentSlot.CPU: entry(profile(ComponentSlot.CPU, tdp_watts=125)),
            ComponentSlot.GPU: entry(profile(ComponentSlot.GPU, power_watts=450)),
            ComponentSlot.PSU: entry(profile(ComponentSlot.PSU, wattage=500)),
        }
    )
    assert "PSU_INSUFFICIENT" in codes(report, "error")


def test_a_psu_with_thin_headroom_warns():
    """
    Above the draw but under the headroom factor. It works; it leaves nothing
    for transient spikes, which is a real risk worth naming.
    """
    report = compatibility.evaluate(
        {
            ComponentSlot.CPU: entry(profile(ComponentSlot.CPU, tdp_watts=65)),
            ComponentSlot.GPU: entry(profile(ComponentSlot.GPU, power_watts=200)),
            # Draw is 75 + 65 + 200 = 340W; 1.3x is 442W.
            ComponentSlot.PSU: entry(profile(ComponentSlot.PSU, wattage=400)),
        }
    )
    assert "PSU_TIGHT" in codes(report, "warning")
    assert report.is_compatible is True


def test_a_comfortably_sized_psu_reports_nothing():
    report = compatibility.evaluate(
        {
            ComponentSlot.CPU: entry(profile(ComponentSlot.CPU, tdp_watts=65)),
            ComponentSlot.GPU: entry(profile(ComponentSlot.GPU, power_watts=200)),
            ComponentSlot.PSU: entry(profile(ComponentSlot.PSU, wattage=650)),
        }
    )
    assert "PSU_TIGHT" not in codes(report)
    assert "PSU_INSUFFICIENT" not in codes(report)


def test_the_power_estimate_sums_draw_over_the_base_system_load():
    report = compatibility.evaluate(
        {
            ComponentSlot.CPU: entry(profile(ComponentSlot.CPU, tdp_watts=65)),
            ComponentSlot.GPU: entry(profile(ComponentSlot.GPU, power_watts=115)),
        }
    )
    assert report.estimated_watts == compatibility.BASE_SYSTEM_WATTS + 65 + 115


def test_quantity_multiplies_a_parts_draw():
    report = compatibility.evaluate(
        {
            ComponentSlot.SSD: entry(
                profile(ComponentSlot.SSD, power_watts=8), quantity=3
            ),
        }
    )
    assert report.estimated_watts == compatibility.BASE_SYSTEM_WATTS + 24


def test_a_guessed_power_figure_is_declared_rather_than_hidden():
    """
    A drive with no published figure falls back to a typical value -- and the
    report says so. A silent default is how a wattage estimate becomes
    confidently wrong.
    """
    report = compatibility.evaluate(
        {ComponentSlot.SSD: entry(profile(ComponentSlot.SSD))}
    )
    assert report.power_is_estimated is True
    assert "POWER_PARTIALLY_ESTIMATED" in codes(report, "info")


def test_peripherals_are_excluded_from_the_power_budget():
    """A monitor is plugged into the wall, not into the build's PSU."""
    report = compatibility.evaluate(
        {
            ComponentSlot.MONITOR: entry(
                profile(ComponentSlot.MONITOR, power_watts=45)
            ),
        }
    )
    assert report.estimated_watts == compatibility.BASE_SYSTEM_WATTS


def test_the_recommended_psu_rounds_up_to_a_size_that_is_actually_sold():
    report = compatibility.evaluate(
        {ComponentSlot.GPU: entry(profile(ComponentSlot.GPU, power_watts=200))}
    )
    # 275W draw x 1.3 = 357.5W, which is not a size anyone sells.
    assert report.recommended_psu_watts in (450, 550, 650, 750, 850, 1000, 1200, 1600)


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------
def test_an_empty_build_is_incomplete_but_not_incompatible():
    """
    The distinction the UI depends on. Greeting someone with a red banner
    before they have chosen anything teaches them to ignore it.
    """
    report = compatibility.evaluate({})
    assert report.is_complete is False
    assert report.is_compatible is True


def test_either_an_ssd_or_a_hard_drive_satisfies_storage():
    base = {
        ComponentSlot.CPU: entry(profile(ComponentSlot.CPU, socket="AM4")),
        ComponentSlot.MOTHERBOARD: entry(
            profile(ComponentSlot.MOTHERBOARD, socket="AM4", ram_type="DDR4")
        ),
        ComponentSlot.RAM: entry(profile(ComponentSlot.RAM, ram_type="DDR4")),
        ComponentSlot.PSU: entry(profile(ComponentSlot.PSU, wattage=650)),
        ComponentSlot.CASE: entry(profile(ComponentSlot.CASE)),
    }

    with_hdd = compatibility.evaluate({**base, ComponentSlot.HDD: entry(profile(ComponentSlot.HDD))})
    assert with_hdd.is_complete is True

    with_ssd = compatibility.evaluate({**base, ComponentSlot.SSD: entry(profile(ComponentSlot.SSD))})
    assert with_ssd.is_complete is True

    assert compatibility.evaluate(base).is_complete is False


def test_a_build_with_no_graphics_card_prompts_about_integrated_graphics():
    report = compatibility.evaluate(
        {ComponentSlot.CPU: entry(profile(ComponentSlot.CPU, socket="AM4"))}
    )
    assert "NO_DISCRETE_GPU" in codes(report, "info")


# ---------------------------------------------------------------------------
# The report contract
# ---------------------------------------------------------------------------
def test_every_report_carries_the_advisory_disclaimer():
    """
    Non-negotiable. These rules are this store's own guidance against the
    specifications it holds, not a manufacturer compatibility guarantee, and
    no response may present them otherwise.
    """
    payload = compatibility.evaluate({}).as_dict()
    assert payload["advisory"]
    assert "not a manufacturer" in payload["advisory"]


@pytest.mark.parametrize(
    "key",
    [
        "is_compatible",
        "is_complete",
        "estimated_watts",
        "recommended_psu_watts",
        "power_is_estimated",
        "missing_slots",
        "findings",
        "advisory",
    ],
)
def test_the_report_shape_is_stable(key):
    assert key in compatibility.evaluate({}).as_dict()


def test_findings_serialise_with_a_level_code_message_and_slots():
    report = compatibility.evaluate(
        {
            ComponentSlot.CPU: entry(profile(ComponentSlot.CPU, socket="AM4")),
            ComponentSlot.MOTHERBOARD: entry(
                profile(ComponentSlot.MOTHERBOARD, socket="AM5")
            ),
        }
    )
    finding = next(f for f in report.as_dict()["findings"] if f["code"] == "SOCKET_MISMATCH")
    assert finding["level"] == "error"
    assert finding["message"]
    # The slots a finding names are what the UI highlights, so both ends of
    # the conflict must be listed.
    assert set(finding["slots"]) == {ComponentSlot.CPU, ComponentSlot.MOTHERBOARD}
