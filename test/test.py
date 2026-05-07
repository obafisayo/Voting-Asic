# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

# True when running gate-level simulation (make GATES=yes)
GL_TEST = os.environ.get("GATES", "no").lower() == "yes"

# ── Constants ──────────────────────────────────────────────────────────────────

# Must match MASTER_LIST in src/voter_id_validator.v
VALID_IDS   = [0xA0001, 0xA0002, 0xA0003, 0xA0004,
               0xB0001, 0xB0002, 0xC0001, 0xD0099]
INVALID_IDS = [0x00000, 0xFFFFF, 0x12345, 0xA0005, 0xD0098]


# ── Shared helpers ─────────────────────────────────────────────────────────────

async def reset(dut):
    """Full reset: initialise every input, hold rst_n low for 5 cycles."""
    dut.ena.value    = 1
    dut.ui_in.value  = 0
    dut.uio_in.value = 0
    if not GL_TEST:
        dut.dc_voter_id.value       = 0
        dut.dc_check_en.value       = 0
        dut.vtc_vote_en.value       = 0
        dut.vtc_candidate_sel.value = 0
    dut.rst_n.value  = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value  = 1
    await ClockCycles(dut.clk, 2)


# ── MOD-02 helpers ─────────────────────────────────────────────────────────────

async def load_voter_id(dut, voter_id):
    """Stream a 20-bit voter ID into the TT wrapper using the two-write protocol."""
    low_byte    =  voter_id        & 0xFF
    mid_byte    = (voter_id >> 8)  & 0xFF
    high_nibble = (voter_id >> 16) & 0xF

    # Write 1: voter_id[7:0]  — byte_sel=01, byte_write=1
    dut.ui_in.value  = low_byte
    dut.uio_in.value = 0b00000101
    await RisingEdge(dut.clk)

    # Write 2: voter_id[15:8] via ui_in, voter_id[19:16] via uio_in[7:4]
    dut.ui_in.value  = mid_byte
    dut.uio_in.value = (high_nibble << 4) | 0b00000110
    await RisingEdge(dut.clk)

    # Deassert write strobe
    dut.ui_in.value  = 0
    dut.uio_in.value = 0
    await RisingEdge(dut.clk)


async def validate(dut, candidate=0):
    """Pulse data_ready with candidate_sel=candidate; return (id_valid, pipeline_done, uo_out).

    Pipeline timing (valid path):
      posedge N   : data_ready sampled, IDLE→VALIDATING, MOD-02 stage1 latches ID
      posedge N+1 : state stays VALIDATING; MOD-02 fires validate_done NBA; next_state→CHECKING
      posedge N+2 : state→CHECKING, check_en registered-pulse fires
      posedge N+3 : state stays CHECKING; MOD-03 fires check_done NBA; next_state→VOTE_CAST
      posedge N+4 : state→VOTE_CAST, vote_en high
      posedge N+5 : state→IDLE
      ReadWrite N+6 (before N+6 NBAs): state = IDLE from N+5 NBA ✓

    Invalid path reaches IDLE at posedge N+3 — also settled by ReadWrite N+6.
    """
    dut.ui_in.value  = candidate & 0x7  # candidate_sel for this vote
    dut.uio_in.value = 0b00001000       # data_ready = uio_in[3]
    await RisingEdge(dut.clk)           # posedge N: data_ready sampled
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 6)       # ReadWrite N+6: full pipeline settled
    out = int(dut.uo_out.value)
    id_valid      = bool(out & 0x08)    # uo_out[3]
    pipeline_done = (out & 0x07) == 0   # uo_out[2:0] == IDLE
    return id_valid, pipeline_done, out


# ── MOD-03 helper ──────────────────────────────────────────────────────────────

async def check_voter(dut, voter_id):
    """Assert check_en for one cycle; return (is_duplicate, check_done).

    check_done is set directly in cycle N's NBA, so it is readable at
    cycle N+1's ReadWrite phase — hence ClockCycles(1).
    """
    dut.dc_voter_id.value = voter_id
    dut.dc_check_en.value = 1
    await RisingEdge(dut.clk)           # Cycle N: check_en sampled, NBA sets outputs
    dut.dc_check_en.value = 0
    await ClockCycles(dut.clk, 1)       # N+1 ReadWrite: N's NBAs visible
    return bool(int(dut.dc_is_duplicate.value)), bool(int(dut.dc_check_done.value))


# ── MOD-04 helper ──────────────────────────────────────────────────────────────

async def cast_vote(dut, candidate):
    """Pulse vote_en for one cycle; return (tally_count, vote_cast).

    vote_cast and the counter increment are both set in cycle N's NBA,
    readable at cycle N+1's ReadWrite — hence ClockCycles(1).
    """
    dut.vtc_candidate_sel.value = candidate
    dut.vtc_vote_en.value       = 1     # 0→1 rising edge triggers vote_event
    await RisingEdge(dut.clk)           # Cycle N: NBA increments counter, sets vote_cast
    dut.vtc_vote_en.value       = 0
    await ClockCycles(dut.clk, 1)       # N+1 ReadWrite: N's NBAs visible
    return int(dut.vtc_tally_out.value), bool(int(dut.vtc_vote_cast.value))


# ── MOD-02 tests ───────────────────────────────────────────────────────────────

@cocotb.test()
async def test_valid_ids(dut):
    """MOD-02: all IDs in the master list must be accepted."""
    dut._log.info("test_valid_ids")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    for voter_id in VALID_IDS:
        await load_voter_id(dut, voter_id)
        id_valid, pipeline_done, _ = await validate(dut)
        assert pipeline_done, f"FSM did not return to IDLE after processing ID {voter_id:#07x}"
        assert id_valid,      f"ID {voter_id:#07x} should be valid but was rejected"
        dut._log.info(f"MOD-02 PASS  {voter_id:#07x}  id_valid={id_valid}")


@cocotb.test()
async def test_invalid_ids(dut):
    """MOD-02: IDs not in the master list must be rejected."""
    dut._log.info("test_invalid_ids")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    for voter_id in INVALID_IDS:
        await load_voter_id(dut, voter_id)
        id_valid, pipeline_done, _ = await validate(dut)
        assert pipeline_done, f"FSM did not return to IDLE after processing ID {voter_id:#07x}"
        assert not id_valid,  f"ID {voter_id:#07x} should be invalid but was accepted"
        dut._log.info(f"MOD-02 PASS  {voter_id:#07x}  id_valid={id_valid}")


@cocotb.test()
async def test_back_to_back(dut):
    """MOD-02: alternating valid/invalid IDs must each return the correct result."""
    dut._log.info("test_back_to_back")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    cases = [
        (0xA0001, True),
        (0xFFFFF, False),
        (0xD0099, True),
        (0x00000, False),
        (0xB0002, True),
    ]
    for voter_id, expect_valid in cases:
        await load_voter_id(dut, voter_id)
        id_valid, _, _ = await validate(dut)
        assert id_valid == expect_valid, (
            f"ID {voter_id:#07x}: expected id_valid={expect_valid}, got {id_valid}"
        )
        dut._log.info(f"MOD-02 PASS  {voter_id:#07x}  id_valid={id_valid}")


# ── MOD-03 tests ───────────────────────────────────────────────────────────────

@cocotb.test(skip=GL_TEST)
async def test_duplicate_checker_first_vote(dut):
    """MOD-03: first submission of registered IDs must NOT be flagged as duplicate."""
    dut._log.info("test_duplicate_checker_first_vote")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    test_ids = [0xA0001, 0xA0002, 0xA0003]
    for vid in test_ids:
        is_dup, done = await check_voter(dut, vid)
        assert done,       f"check_done did not pulse for ID {vid:#07x}"
        assert not is_dup, f"ID {vid:#07x} flagged as duplicate on first submission"
        dut._log.info(f"MOD-03 PASS  {vid:#07x}  is_duplicate={is_dup} (first vote)")


@cocotb.test(skip=GL_TEST)
async def test_duplicate_checker_second_vote(dut):
    """MOD-03: submitting the same voter ID twice within one session must be blocked."""
    dut._log.info("test_duplicate_checker_second_vote")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    vid = 0xA0004
    is_dup, done = await check_voter(dut, vid)
    assert done and not is_dup, f"First vote for {vid:#07x} should not be duplicate"
    dut._log.info(f"MOD-03 PASS  {vid:#07x}  first vote accepted")

    is_dup, done = await check_voter(dut, vid)
    assert done and is_dup, f"Second vote for {vid:#07x} should be flagged as duplicate"
    dut._log.info(f"MOD-03 PASS  {vid:#07x}  second vote blocked")


@cocotb.test(skip=GL_TEST)
async def test_duplicate_checker_new_vs_repeat(dut):
    """MOD-03: fresh ID accepted then blocked on repeat — within a single test."""
    dut._log.info("test_duplicate_checker_new_vs_repeat")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    vid = 0xB0001
    is_dup, done = await check_voter(dut, vid)
    assert done and not is_dup, f"First vote for {vid:#07x} should not be duplicate"
    dut._log.info(f"MOD-03 PASS  {vid:#07x}  first vote accepted")

    is_dup, done = await check_voter(dut, vid)
    assert done and is_dup, f"Second vote for {vid:#07x} should be duplicate"
    dut._log.info(f"MOD-03 PASS  {vid:#07x}  second vote blocked")


# ── MOD-04 tests ───────────────────────────────────────────────────────────────

@cocotb.test(skip=GL_TEST)
async def test_vote_tally_single_candidate(dut):
    """MOD-04: repeated votes for the same candidate accumulate correctly."""
    dut._log.info("test_vote_tally_single_candidate")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    for expected_count in range(1, 5):
        tally, vote_cast = await cast_vote(dut, candidate=0)
        assert vote_cast, f"vote_cast did not pulse on vote {expected_count}"
        assert tally == expected_count, (
            f"After {expected_count} votes for candidate 0: expected tally={expected_count}, got {tally}"
        )
        dut._log.info(f"MOD-04 PASS  candidate=0  tally={tally}")


@cocotb.test(skip=GL_TEST)
async def test_vote_tally_multiple_candidates(dut):
    """MOD-04: votes for different candidates go into separate counters."""
    dut._log.info("test_vote_tally_multiple_candidates")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    for _ in range(2):
        await cast_vote(dut, candidate=1)
    for _ in range(3):
        await cast_vote(dut, candidate=5)

    tally1, _ = await cast_vote(dut, candidate=1)   # one more → should be 3 total
    tally5, _ = await cast_vote(dut, candidate=5)   # one more → should be 4 total

    assert tally1 == 3, f"Candidate 1: expected 3 votes, got {tally1}"
    assert tally5 == 4, f"Candidate 5: expected 4 votes, got {tally5}"
    dut._log.info(f"MOD-04 PASS  candidate=1 tally={tally1}, candidate=5 tally={tally5}")


@cocotb.test(skip=GL_TEST)
async def test_vote_tally_no_spurious_votes(dut):
    """MOD-04: holding vote_en high after the rising edge must NOT double-count."""
    dut._log.info("test_vote_tally_no_spurious_votes")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    dut.vtc_candidate_sel.value = 2
    dut.vtc_vote_en.value       = 1        # 0→1 edge
    await RisingEdge(dut.clk)              # vote_event fires
    # Hold vote_en high for 3 more cycles — must NOT produce extra votes
    await ClockCycles(dut.clk, 3)
    dut.vtc_vote_en.value = 0
    await ClockCycles(dut.clk, 1)

    tally = int(dut.vtc_tally_out.value)
    assert tally == 1, f"Expected exactly 1 vote for candidate 2, got {tally}"
    dut._log.info(f"MOD-04 PASS  candidate=2 tally={tally} (no spurious counts)")


# ── FSM integration tests (via TT wrapper) ────────────────────────────────────

@cocotb.test()
async def test_fsm_invalid_path(dut):
    """Integration: invalid voter ID must put FSM into INVALID state (status=101)."""
    dut._log.info("test_fsm_invalid_path")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    await load_voter_id(dut, 0x12345)
    id_valid, pipeline_done, out = await validate(dut)

    assert pipeline_done,  "FSM did not return to IDLE after INVALID ID"
    assert not id_valid,   "INVALID ID must not set id_valid"
    is_dup = bool(out & 0x10)
    assert not is_dup,     "is_duplicate must stay 0 for invalid ID (checker never ran)"
    dut._log.info(f"FSM PASS  0x12345  id_valid={id_valid}  pipeline_done={pipeline_done}")


@cocotb.test()
async def test_fsm_duplicate_path(dut):
    """Integration: submitting the same valid voter ID twice must yield DUPLICATE on second."""
    dut._log.info("test_fsm_duplicate_path")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    vid = 0xC0001   # valid, registered

    # First vote — must be accepted
    await load_voter_id(dut, vid)
    id_valid1, done1, out1 = await validate(dut)
    assert done1 and id_valid1, f"First vote for {vid:#07x} should be accepted"
    is_dup1 = bool(out1 & 0x10)
    assert not is_dup1, "First vote must NOT set is_duplicate"
    dut._log.info(f"FSM PASS  {vid:#07x}  first vote accepted")

    # Second vote — same ID, must be blocked
    await load_voter_id(dut, vid)
    id_valid2, done2, out2 = await validate(dut)
    assert done2,      "FSM must return to IDLE after DUPLICATE"
    assert id_valid2,  "id_valid must still be 1 (voter is registered, just already voted)"
    is_dup2 = bool(out2 & 0x10)
    assert is_dup2,    "Second vote must set is_duplicate"
    dut._log.info(f"FSM PASS  {vid:#07x}  second vote blocked (is_duplicate=1)")


@cocotb.test()
async def test_tally_readback(dut):
    """Integration: after voting for a candidate, uo_out[7:5] shows the correct tally."""
    dut._log.info("test_tally_readback")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    # Vote for candidate 5 with voter 0xB0002
    await load_voter_id(dut, 0xB0002)
    id_valid, done, _ = await validate(dut, candidate=5)
    assert done and id_valid, "Vote should be accepted"

    # In IDLE, set ui_in[2:0]=5 to select candidate 5's counter
    dut.ui_in.value = 5
    await ClockCycles(dut.clk, 1)
    out = int(dut.uo_out.value)
    tally = (out >> 5) & 0x7        # uo_out[7:5]
    assert tally == 1, f"Expected tally=1 for candidate 5, got {tally}"
    dut._log.info(f"Tally PASS  candidate=5  tally={tally}")

    # Vote again for candidate 5 with voter 0xD0099
    await load_voter_id(dut, 0xD0099)
    id_valid2, done2, _ = await validate(dut, candidate=5)
    assert done2 and id_valid2

    dut.ui_in.value = 5
    await ClockCycles(dut.clk, 1)
    out2 = int(dut.uo_out.value)
    tally2 = (out2 >> 5) & 0x7
    assert tally2 == 2, f"Expected tally=2 for candidate 5 after second vote, got {tally2}"
    dut._log.info(f"Tally PASS  candidate=5  tally={tally2} after 2 votes")
