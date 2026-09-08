"""
PC-builder compatibility rules.

**These rules are this application's own logic, not a manufacturer
compatibility list.** They compare the normalised fields on
`catalog.ComponentProfile` and nothing else, so they catch the four or five
mistakes that actually strand a first-time builder -- wrong socket, wrong
memory generation, a board that will not fit the case, a power supply that
cannot carry the card -- and they say nothing at all about the dozens of
subtler ones (BIOS revisions, memory QVLs, chipset lane budgets, radiator
clearance). Every verdict this module returns is therefore advisory, and the
API and UI label it that way. A build that passes here is *plausible*, not
certified.

The second deliberate choice: **missing data is reported, never assumed.**
When a part carries no `tdp_watts`, the estimator says so rather than
substituting a guess, because a silent default is how a wattage estimate
becomes confidently wrong. Findings therefore come in three levels --
`error` (two known values genuinely conflict), `warning` (a real risk, e.g.
thin PSU headroom), and `info` (a check could not run because a value is
absent).
"""
from dataclasses import dataclass, field

from apps.catalog.models import ComponentSlot

# --------------------------------------------------------------------------
# Slot policy
# --------------------------------------------------------------------------

# What a machine needs before it will POST. Storage is handled separately:
# either an SSD or an HDD satisfies it, so neither is individually required.
REQUIRED_SLOTS = (
    ComponentSlot.CPU,
    ComponentSlot.MOTHERBOARD,
    ComponentSlot.RAM,
    ComponentSlot.PSU,
    ComponentSlot.CASE,
)

STORAGE_SLOTS = (ComponentSlot.SSD, ComponentSlot.HDD)

# Peripherals -- never required, never part of the power budget.
PERIPHERAL_SLOTS = (
    ComponentSlot.MONITOR,
    ComponentSlot.KEYBOARD,
    ComponentSlot.MOUSE,
)

# The order the builder renders slots in: the dependency chain first (a socket
# is chosen by picking a CPU, so the CPU comes before the board), then
# storage, then the parts that only need to fit, then peripherals.
SLOT_ORDER = (
    ComponentSlot.CPU,
    ComponentSlot.COOLER,
    ComponentSlot.MOTHERBOARD,
    ComponentSlot.RAM,
    ComponentSlot.GPU,
    ComponentSlot.SSD,
    ComponentSlot.HDD,
    ComponentSlot.PSU,
    ComponentSlot.CASE,
    ComponentSlot.MONITOR,
    ComponentSlot.KEYBOARD,
    ComponentSlot.MOUSE,
)

# --------------------------------------------------------------------------
# Power model
# --------------------------------------------------------------------------

# Draw for the parts nobody itemises: board, fans, USB devices, and the drives
# when their own figure is missing. A flat number rather than a per-part model
# because the estimate's error bars are far wider than the difference.
BASE_SYSTEM_WATTS = 75

# Fallbacks used ONLY when a profile carries no figure of its own. Each use is
# reported as an `info` finding, so a total built on guesses says so.
FALLBACK_WATTS = {
    ComponentSlot.SSD: 8,
    ComponentSlot.HDD: 12,
}

# A PSU should not run pinned at its rating: efficiency peaks near half load
# and transient spikes on a modern GPU go well past the steady-state figure.
# Below this multiple of estimated draw we warn; the shortfall itself is an
# error.
PSU_HEADROOM_FACTOR = 1.3


@dataclass
class Finding:
    """One thing the checker noticed. `level` is error | warning | info."""

    level: str
    code: str
    message: str
    slots: tuple = ()

    def as_dict(self):
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "slots": list(self.slots),
        }


@dataclass
class BuildReport:
    findings: list = field(default_factory=list)
    estimated_watts: int = 0
    recommended_psu_watts: int = 0
    missing_slots: list = field(default_factory=list)
    power_is_estimated: bool = False

    @property
    def errors(self):
        return [f for f in self.findings if f.level == "error"]

    @property
    def is_compatible(self):
        """
        True when no rule was *violated*.

        Note what this deliberately does not include: a build missing its
        motherboard is not "incompatible", it is incomplete. `is_complete`
        answers that, and the UI shows the two separately -- otherwise an
        empty builder greets you with a red banner.
        """
        return not self.errors

    @property
    def is_complete(self):
        return not self.missing_slots

    def as_dict(self):
        return {
            "is_compatible": self.is_compatible,
            "is_complete": self.is_complete,
            "estimated_watts": self.estimated_watts,
            "recommended_psu_watts": self.recommended_psu_watts,
            "power_is_estimated": self.power_is_estimated,
            "missing_slots": list(self.missing_slots),
            "findings": [f.as_dict() for f in self.findings],
            # Restated on every response so no client can present the verdict
            # as authoritative by accident.
            "advisory": (
                "Compatibility checks are this store's own guidance, based on "
                "the specifications we hold. They are not a manufacturer "
                "compatibility guarantee -- confirm critical fitment with the "
                "manufacturer before you buy."
            ),
        }


def _norm(value):
    """Sockets and memory types are compared case- and space-insensitively."""
    return (value or "").strip().lower().replace(" ", "").replace("-", "")


def _profile(selection, slot):
    entry = selection.get(slot)
    return entry.get("profile") if entry else None


def _name(selection, slot):
    entry = selection.get(slot)
    return entry.get("name") if entry else slot


# --------------------------------------------------------------------------
# Individual rules
#
# Each takes the whole selection and appends findings. They are written to be
# independently readable and to no-op when their inputs are absent, so adding
# or removing one never disturbs the others.
# --------------------------------------------------------------------------


def _check_cpu_socket(selection, findings):
    cpu, board = _profile(selection, ComponentSlot.CPU), _profile(
        selection, ComponentSlot.MOTHERBOARD
    )
    if not (cpu and board):
        return
    if not cpu.socket or not board.socket:
        findings.append(
            Finding(
                "info",
                "SOCKET_UNKNOWN",
                "We do not hold a socket for one of these parts, so the "
                "processor/motherboard fit was not checked.",
                (ComponentSlot.CPU, ComponentSlot.MOTHERBOARD),
            )
        )
        return
    if _norm(cpu.socket) != _norm(board.socket):
        findings.append(
            Finding(
                "error",
                "SOCKET_MISMATCH",
                f"{_name(selection, ComponentSlot.CPU)} uses socket "
                f"{cpu.socket}, but {_name(selection, ComponentSlot.MOTHERBOARD)} "
                f"has socket {board.socket}. They will not fit together.",
                (ComponentSlot.CPU, ComponentSlot.MOTHERBOARD),
            )
        )


def _check_cooler(selection, findings):
    cooler = _profile(selection, ComponentSlot.COOLER)
    cpu = _profile(selection, ComponentSlot.CPU)
    if not cooler:
        # Not an error: many retail CPUs ship with a cooler, and we cannot
        # tell from here which do.
        if cpu and cpu.tdp_watts and cpu.tdp_watts >= 125:
            findings.append(
                Finding(
                    "warning",
                    "COOLER_RECOMMENDED",
                    f"{_name(selection, ComponentSlot.CPU)} is a "
                    f"{cpu.tdp_watts}W processor. Check whether it includes a "
                    "cooler; at this power level an aftermarket one is usually "
                    "needed.",
                    (ComponentSlot.COOLER,),
                )
            )
        return

    if cpu and cpu.socket and cooler.supported_sockets:
        supported = {_norm(s) for s in cooler.supported_sockets}
        if _norm(cpu.socket) not in supported:
            findings.append(
                Finding(
                    "error",
                    "COOLER_SOCKET_MISMATCH",
                    f"{_name(selection, ComponentSlot.COOLER)} does not list "
                    f"socket {cpu.socket} among the mounts it supports.",
                    (ComponentSlot.COOLER, ComponentSlot.CPU),
                )
            )

    if cpu and cpu.tdp_watts and cooler.cooler_max_tdp_watts:
        if cooler.cooler_max_tdp_watts < cpu.tdp_watts:
            findings.append(
                Finding(
                    "warning",
                    "COOLER_UNDERSIZED",
                    f"{_name(selection, ComponentSlot.COOLER)} is rated to "
                    f"{cooler.cooler_max_tdp_watts}W but "
                    f"{_name(selection, ComponentSlot.CPU)} can draw "
                    f"{cpu.tdp_watts}W. Expect throttling under sustained load.",
                    (ComponentSlot.COOLER, ComponentSlot.CPU),
                )
            )

    case = _profile(selection, ComponentSlot.CASE)
    if case and case.max_cooler_height_mm and cooler.height_mm:
        if cooler.height_mm > case.max_cooler_height_mm:
            findings.append(
                Finding(
                    "error",
                    "COOLER_TOO_TALL",
                    f"{_name(selection, ComponentSlot.COOLER)} is "
                    f"{cooler.height_mm}mm tall; "
                    f"{_name(selection, ComponentSlot.CASE)} takes at most "
                    f"{case.max_cooler_height_mm}mm.",
                    (ComponentSlot.COOLER, ComponentSlot.CASE),
                )
            )


def _check_memory(selection, findings):
    ram, board = _profile(selection, ComponentSlot.RAM), _profile(
        selection, ComponentSlot.MOTHERBOARD
    )
    if not (ram and board):
        return

    if ram.ram_type and board.ram_type:
        if _norm(ram.ram_type) != _norm(board.ram_type):
            findings.append(
                Finding(
                    "error",
                    "RAM_TYPE_MISMATCH",
                    f"{_name(selection, ComponentSlot.RAM)} is {ram.ram_type}, "
                    f"but {_name(selection, ComponentSlot.MOTHERBOARD)} takes "
                    f"{board.ram_type}. The two are not interchangeable -- the "
                    "modules are physically keyed differently.",
                    (ComponentSlot.RAM, ComponentSlot.MOTHERBOARD),
                )
            )
    else:
        findings.append(
            Finding(
                "info",
                "RAM_TYPE_UNKNOWN",
                "We do not hold a memory type for one of these parts, so the "
                "memory fit was not checked.",
                (ComponentSlot.RAM, ComponentSlot.MOTHERBOARD),
            )
        )

    quantity = (selection.get(ComponentSlot.RAM) or {}).get("quantity", 1)
    if ram.module_count and board.ram_slots:
        needed = ram.module_count * quantity
        if needed > board.ram_slots:
            findings.append(
                Finding(
                    "error",
                    "RAM_SLOTS_EXCEEDED",
                    f"That is {needed} memory modules, but "
                    f"{_name(selection, ComponentSlot.MOTHERBOARD)} has "
                    f"{board.ram_slots} slots.",
                    (ComponentSlot.RAM, ComponentSlot.MOTHERBOARD),
                )
            )

    if ram.capacity_gb and board.max_ram_gb:
        total = ram.capacity_gb * quantity
        if total > board.max_ram_gb:
            findings.append(
                Finding(
                    "error",
                    "RAM_CAPACITY_EXCEEDED",
                    f"{total}GB exceeds the {board.max_ram_gb}GB maximum "
                    f"{_name(selection, ComponentSlot.MOTHERBOARD)} supports.",
                    (ComponentSlot.RAM, ComponentSlot.MOTHERBOARD),
                )
            )


def _check_case_fit(selection, findings):
    case, board = _profile(selection, ComponentSlot.CASE), _profile(
        selection, ComponentSlot.MOTHERBOARD
    )
    if case and board:
        if board.form_factor and case.supported_form_factors:
            supported = {_norm(f) for f in case.supported_form_factors}
            if _norm(board.form_factor) not in supported:
                findings.append(
                    Finding(
                        "error",
                        "FORM_FACTOR_MISMATCH",
                        f"{_name(selection, ComponentSlot.CASE)} accepts "
                        f"{', '.join(case.supported_form_factors)} boards; "
                        f"{_name(selection, ComponentSlot.MOTHERBOARD)} is "
                        f"{board.form_factor}.",
                        (ComponentSlot.CASE, ComponentSlot.MOTHERBOARD),
                    )
                )
        elif not board.form_factor or not case.supported_form_factors:
            findings.append(
                Finding(
                    "info",
                    "FORM_FACTOR_UNKNOWN",
                    "We do not hold a form factor for one of these parts, so "
                    "the board/case fit was not checked.",
                    (ComponentSlot.CASE, ComponentSlot.MOTHERBOARD),
                )
            )

    gpu = _profile(selection, ComponentSlot.GPU)
    if case and gpu and gpu.length_mm and case.max_gpu_length_mm:
        if gpu.length_mm > case.max_gpu_length_mm:
            findings.append(
                Finding(
                    "error",
                    "GPU_TOO_LONG",
                    f"{_name(selection, ComponentSlot.GPU)} is "
                    f"{gpu.length_mm}mm long; "
                    f"{_name(selection, ComponentSlot.CASE)} takes at most "
                    f"{case.max_gpu_length_mm}mm.",
                    (ComponentSlot.GPU, ComponentSlot.CASE),
                )
            )


def estimate_power(selection, findings):
    """
    Steady-state draw, in watts, plus whether any part of it was guessed.

    Deliberately *not* a peak-power model: transient spikes on a modern GPU
    can be double its rated draw for milliseconds, which is a PSU-quality
    question this store holds no data to answer. The headroom factor below is
    what stands in for it.
    """
    total = BASE_SYSTEM_WATTS
    guessed = False

    for slot, entry in selection.items():
        if slot in PERIPHERAL_SLOTS:
            continue
        profile = entry.get("profile")
        if profile is None:
            continue
        quantity = entry.get("quantity", 1)

        # A CPU's TDP is its power figure; everything else uses power_watts.
        watts = profile.power_watts or profile.tdp_watts

        if watts is None:
            fallback = FALLBACK_WATTS.get(slot)
            if fallback is None:
                continue
            watts, guessed = fallback, True

        total += watts * quantity

    if guessed:
        findings.append(
            Finding(
                "info",
                "POWER_PARTIALLY_ESTIMATED",
                "Some parts in this build carry no power figure, so typical "
                "values were used. Treat the total as an estimate.",
                (),
            )
        )

    return total, guessed


def _check_psu(selection, findings, estimated_watts):
    psu = _profile(selection, ComponentSlot.PSU)
    if not psu:
        return
    if not psu.wattage:
        findings.append(
            Finding(
                "info",
                "PSU_WATTAGE_UNKNOWN",
                "We do not hold a wattage for this power supply, so it was "
                "not checked against the build.",
                (ComponentSlot.PSU,),
            )
        )
        return

    if psu.wattage < estimated_watts:
        findings.append(
            Finding(
                "error",
                "PSU_INSUFFICIENT",
                f"{_name(selection, ComponentSlot.PSU)} supplies "
                f"{psu.wattage}W, below this build's estimated {estimated_watts}W "
                "draw. The system may fail to start or shut down under load.",
                (ComponentSlot.PSU,),
            )
        )
    elif psu.wattage < estimated_watts * PSU_HEADROOM_FACTOR:
        findings.append(
            Finding(
                "warning",
                "PSU_TIGHT",
                f"{_name(selection, ComponentSlot.PSU)} supplies "
                f"{psu.wattage}W against an estimated {estimated_watts}W draw. "
                "That works, but leaves little headroom for transient spikes "
                f"or an upgrade -- around "
                f"{_round_up_psu(estimated_watts * PSU_HEADROOM_FACTOR)}W would "
                "be more comfortable.",
                (ComponentSlot.PSU,),
            )
        )


def _round_up_psu(watts):
    """Round to the next size power supplies are actually sold in."""
    for size in (350, 450, 550, 650, 750, 850, 1000, 1200, 1600):
        if watts <= size:
            return size
    return 1600


def _check_completeness(selection):
    missing = [slot for slot in REQUIRED_SLOTS if slot not in selection]
    if not any(slot in selection for slot in STORAGE_SLOTS):
        # Reported as SSD, since that is the one a new build should have.
        missing.append(ComponentSlot.SSD)
    return missing


def _check_integrated_graphics(selection, findings):
    """
    A build with no graphics card is fine *if* the CPU has integrated
    graphics -- but we hold no field saying whether it does, so this is a
    prompt rather than a verdict.
    """
    if ComponentSlot.GPU in selection or ComponentSlot.CPU not in selection:
        return
    findings.append(
        Finding(
            "info",
            "NO_DISCRETE_GPU",
            "No graphics card selected. This build will only produce a "
            "display if the processor has integrated graphics -- check its "
            "specification before ordering.",
            (ComponentSlot.GPU,),
        )
    )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def evaluate(selection):
    """
    Run every rule over a selection and return a `BuildReport`.

    `selection` maps a slot to
    `{"profile": ComponentProfile | None, "name": str, "quantity": int}`.
    Pure: it touches no database and mutates nothing, so callers are free to
    run it per keystroke.
    """
    findings = []

    _check_cpu_socket(selection, findings)
    _check_cooler(selection, findings)
    _check_memory(selection, findings)
    _check_case_fit(selection, findings)
    _check_integrated_graphics(selection, findings)

    estimated_watts, guessed = estimate_power(selection, findings)
    _check_psu(selection, findings, estimated_watts)

    return BuildReport(
        findings=findings,
        estimated_watts=estimated_watts,
        recommended_psu_watts=_round_up_psu(estimated_watts * PSU_HEADROOM_FACTOR),
        missing_slots=_check_completeness(selection),
        power_is_estimated=guessed,
    )
