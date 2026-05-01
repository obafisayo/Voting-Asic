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
    """Full reset: initialise every input to 0, hold rst_n low for 5 cycles."""
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
    """Stream a 20-bit voter ID into the MOD-02 wrapper using the two-write protocol."""
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


async def validate(dut):
    """Pulse data_ready; return (id_valid, validate_done).

    validate_done is set in cycle N+1's NBA (2-stage pipeline), so it becomes
    readable at cycle N+2's ReadWrite phase — hence ClockCycles(2).
    """
    dut.uio_in.value = 0b00001000       # data_ready = uio_in[3]
    await RisingEdge(dut.clk)           # Cycle N: data_ready sampled
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 2)       # N+2 ReadWrite: N+1's NBAs committed
    out = int(dut.uo_out.value)
    return bool(out & 0x1), bool(out & 0x2)


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
        id_valid, validate_done = await validate(dut)
        assert validate_done, f"validate_done did not pulse for ID {voter_id:#07x}"
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
        id_valid, validate_done = await validate(dut)
        assert validate_done, f"validate_done did not pulse for ID {voter_id:#07x}"
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
        id_valid, _ = await validate(dut)
        assert id_valid == expect_valid, (
            f"ID {voter_id:#07x}: expected id_valid={expect_valid}, got {id_valid}"
        )
        dut._log.info(f"MOD-02 PASS  {voter_id:#07x}  id_valid={id_valid}")


# ── MOD-03 tests ───────────────────────────────────────────────────────────────

@cocotb.test(skip=GL_TEST)
async def test_duplicate_checker_first_vote(dut):
    """MOD-03: a voter's first submission must NOT be flagged as duplicate."""
    dut._log.info("test_duplicate_checker_first_vote")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    # Use IDs in the 0xE0000 range — distinct from MOD-02 master list
    test_ids = [0xE0001, 0xE0002, 0xE0003]
    for vid in test_ids:
        is_dup, done = await check_voter(dut, vid)
        assert done,     f"check_done did not pulse for ID {vid:#07x}"
        assert not is_dup, f"ID {vid:#07x} flagged as duplicate on first submission"
        dut._log.info(f"MOD-03 PASS  {vid:#07x}  is_duplicate={is_dup} (first vote)")


@cocotb.test(skip=GL_TEST)
async def test_duplicate_checker_second_vote(dut):
    """MOD-03: a voter who already voted must be flagged as duplicate."""
    dut._log.info("test_duplicate_checker_second_vote")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    # IDs 0xE0001-0xE0003 were voted in the previous test (same simulation).
    # Submit them again — all must be flagged as duplicates.
    test_ids = [0xE0001, 0xE0002, 0xE0003]
    for vid in test_ids:
        is_dup, done = await check_voter(dut, vid)
        assert done,   f"check_done did not pulse for ID {vid:#07x}"
        assert is_dup, f"ID {vid:#07x} NOT flagged as duplicate on second submission"
        dut._log.info(f"MOD-03 PASS  {vid:#07x}  is_duplicate={is_dup} (second vote blocked)")


@cocotb.test(skip=GL_TEST)
async def test_duplicate_checker_new_vs_repeat(dut):
    """MOD-03: fresh IDs pass while already-voted IDs are blocked in the same session."""
    dut._log.info("test_duplicate_checker_new_vs_repeat")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    # 0xE0010 is new; submit it twice to confirm both paths in one test
    fresh_id  = 0xE0010
    is_dup, done = await check_voter(dut, fresh_id)
    assert done and not is_dup, f"First vote for {fresh_id:#07x} should not be duplicate"
    dut._log.info(f"MOD-03 PASS  {fresh_id:#07x}  first vote accepted")

    is_dup, done = await check_voter(dut, fresh_id)
    assert done and is_dup, f"Second vote for {fresh_id:#07x} should be duplicate"
    dut._log.info(f"MOD-03 PASS  {fresh_id:#07x}  second vote blocked")


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

    # Cast 2 votes for candidate 1, 3 votes for candidate 5
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

    # Rising edge on candidate 2 → expect exactly 1 vote
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
