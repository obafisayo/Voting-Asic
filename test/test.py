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

# Standalone UART instance parameters (tb.v uart_inst: CLK_FREQ=20, BAUD_RATE=1)
# BAUD_DIV = CLK_FREQ / BAUD_RATE = 20 clocks per bit.
# Why 20 and not 10: with BAUD_DIV=10 the DATA state samples every BAUD_DIV+1=11
# cycles (one extra clock for the baud_cnt reload), so bit 7 is sampled 11 cycles
# after its ideal center.  The stop bit enters rx_sync 2 cycles after it is driven,
# meaning the UART reads the stop bit (always 1) as bit 7 — corrupting every byte.
# BAUD_DIV≥14 keeps bit 7 within the valid window; 20 gives comfortable margin.
FAST_BAUD_DIV = 20


# ── Shared helpers ─────────────────────────────────────────────────────────────

async def reset(dut):
    """Full reset: initialise every input, hold rst_n low for 5 cycles."""
    dut.ena.value    = 1
    dut.ui_in.value  = 0
    dut.uio_in.value = 0
    if not GL_TEST:
        dut.uart_rx_in.value        = 1    # UART line idle-high between transmissions
        dut.dc_voter_id.value       = 0
        dut.dc_check_en.value       = 0
        dut.vtc_vote_en.value       = 0
        dut.vtc_candidate_sel.value = 0
    dut.rst_n.value  = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value  = 1
    await ClockCycles(dut.clk, 2)


# ── MOD-02 / integration helpers ───────────────────────────────────────────────

async def load_voter_id(dut, voter_id):
    """Load a 20-bit voter ID into the TT wrapper via the byte-write bus.

    Two-cycle parallel write protocol:
      Step 1: ui_in = voter_id[7:0],  uio_in = 0b0000_0101  (byte_sel=01, byte_write=1)
      Step 2: ui_in = voter_id[15:8], uio_in = (voter_id[18:16]<<4)|0b0000_0110
              Note: uio_in[7] is the UART_RX line, so voter_id[19] is not
              writable via this path.  All 8 master-list IDs have bit 19 = 1,
              so use the UART path (uart_send_voter_id via uio_in[7]) for full
              20-bit delivery; use this path for the 19-bit ids that match
              because the validator uses all 20 bits (bit 19 stays 0 here).
    """
    low_byte    =  voter_id        & 0xFF
    mid_byte    = (voter_id >>  8) & 0xFF
    high_nibble = (voter_id >> 16) & 0xF   # voter_id[19:16]; bit19=1 keeps uio[7]=1 (UART idle)

    # Write 1: voter_id[7:0]
    dut.ui_in.value  = low_byte
    dut.uio_in.value = 0b00000101           # byte_sel=01, byte_write=1
    await RisingEdge(dut.clk)

    # Write 2: voter_id[15:8] + voter_id[19:16] via uio_in[7:4]
    dut.ui_in.value  = mid_byte
    dut.uio_in.value = (high_nibble << 4) | 0b00000110  # byte_sel=10, byte_write=1
    await RisingEdge(dut.clk)

    # Deassert write strobe
    dut.ui_in.value  = 0
    dut.uio_in.value = 0
    await RisingEdge(dut.clk)


async def validate(dut, candidate=0):
    """Pulse data_ready with candidate_sel=candidate; return (id_valid, pipeline_done, uo_out).

    Pipeline timing (valid path):
      posedge N   : data_ready sampled, IDLE→VALIDATING, MOD-02 stage1 latches ID
      posedge N+1 : state stays VALIDATING; MOD-02 fires validate_done NBA
      posedge N+2 : state→CHECKING, check_en pulse fires
      posedge N+3 : state stays CHECKING; MOD-03 fires check_done NBA
      posedge N+4 : state→VOTE_CAST, vote_en high
      posedge N+5 : state→IDLE
      ReadWrite N+6: state = IDLE from N+5 NBA ✓

    Invalid path reaches IDLE at posedge N+3 — also settled by ReadWrite N+6.
    """
    dut.ui_in.value  = candidate & 0x7  # candidate_sel
    dut.uio_in.value = 0b00001000       # data_ready = uio_in[3]
    await RisingEdge(dut.clk)           # posedge N
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 6)       # ReadWrite N+6: full pipeline settled
    out = int(dut.uo_out.value)
    id_valid      = bool(out & 0x08)    # uo_out[3]
    pipeline_done = (out & 0x07) == 0   # uo_out[2:0] == IDLE
    return id_valid, pipeline_done, out


# ── MOD-03 helper ──────────────────────────────────────────────────────────────

async def check_voter(dut, voter_id):
    """Assert check_en for one cycle on the standalone dc_inst; return (is_duplicate, check_done)."""
    dut.dc_voter_id.value = voter_id
    dut.dc_check_en.value = 1
    await RisingEdge(dut.clk)
    dut.dc_check_en.value = 0
    await ClockCycles(dut.clk, 1)       # N+1 ReadWrite: N's NBAs visible
    return bool(int(dut.dc_is_duplicate.value)), bool(int(dut.dc_check_done.value))


# ── MOD-04 helper ──────────────────────────────────────────────────────────────

async def cast_vote(dut, candidate):
    """Pulse vote_en on the standalone vtc_inst; return (tally_count, vote_cast)."""
    dut.vtc_candidate_sel.value = candidate
    dut.vtc_vote_en.value       = 1
    await RisingEdge(dut.clk)
    dut.vtc_vote_en.value       = 0
    await ClockCycles(dut.clk, 1)
    return int(dut.vtc_tally_out.value), bool(int(dut.vtc_vote_cast.value))


# ── MOD-01 UART helpers ────────────────────────────────────────────────────────

async def uart_send_byte(dut, byte_val):
    """Drive one 8N1 frame on uart_rx_in at FAST_BAUD_DIV clocks/bit.

    Bit order: start bit (low), 8 data bits LSB-first, stop bit (high),
    then one extra BAUD_DIV idle period.

    WHY the idle gap: with BAUD_DIV=10 the UART STOP-state counter takes
    107 cycles from frame start to fire byte_done, but 10 bits × 10 clocks
    = 100 cycles.  Without the gap the next start bit arrives 7 cycles
    before the UART returns to IDLE, so frame N+1's start-bit detection is
    delayed and all sample points shift by ~1 bit, corrupting the byte.
    One extra BAUD_DIV (10 clocks) of idle is enough margin.
    """
    dut.uart_rx_in.value = 0                        # start bit
    await ClockCycles(dut.clk, FAST_BAUD_DIV)
    for i in range(8):
        dut.uart_rx_in.value = (byte_val >> i) & 1  # data bits LSB first
        await ClockCycles(dut.clk, FAST_BAUD_DIV)
    dut.uart_rx_in.value = 1                         # stop bit + idle
    await ClockCycles(dut.clk, FAST_BAUD_DIV * 2)   # stop bit (1×) + idle gap (1×)


async def uart_send_voter_id(dut, voter_id):
    """Transmit a 20-bit voter ID as 3 successive 8N1 frames.

    Frame 0: voter_id[7:0]    (low byte)
    Frame 1: voter_id[15:8]   (mid byte)
    Frame 2: voter_id[19:16]  (high nibble, upper 4 bits ignored by receiver)
    """
    await uart_send_byte(dut, voter_id & 0xFF)
    await uart_send_byte(dut, (voter_id >> 8) & 0xFF)
    await uart_send_byte(dut, (voter_id >> 16) & 0xF)


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
    """MOD-03: submitting the same voter ID twice must be blocked."""
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
    """MOD-03: fresh ID accepted then blocked on repeat."""
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

    tally1, _ = await cast_vote(dut, candidate=1)
    tally5, _ = await cast_vote(dut, candidate=5)

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
    dut.vtc_vote_en.value       = 1
    await RisingEdge(dut.clk)
    await ClockCycles(dut.clk, 3)
    dut.vtc_vote_en.value = 0
    await ClockCycles(dut.clk, 1)

    tally = int(dut.vtc_tally_out.value)
    assert tally == 1, f"Expected exactly 1 vote for candidate 2, got {tally}"
    dut._log.info(f"MOD-04 PASS  candidate=2 tally={tally} (no spurious counts)")


# ── FSM integration tests (via TT wrapper) ─────────────────────────────────────

@cocotb.test()
async def test_fsm_invalid_path(dut):
    """Integration: invalid voter ID must reach INVALID state then return to IDLE."""
    dut._log.info("test_fsm_invalid_path")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    await load_voter_id(dut, 0x12345)
    id_valid, pipeline_done, out = await validate(dut)

    assert pipeline_done, "FSM did not return to IDLE after INVALID ID"
    assert not id_valid,  "INVALID ID must not set id_valid"
    assert not bool(out & 0x10), "is_duplicate must stay 0 (duplicate checker never ran)"
    dut._log.info(f"FSM PASS  0x12345  id_valid={id_valid}  pipeline_done={pipeline_done}")


@cocotb.test()
async def test_fsm_duplicate_path(dut):
    """Integration: submitting the same valid voter ID twice must yield DUPLICATE on second."""
    dut._log.info("test_fsm_duplicate_path")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    vid = 0xC0001

    await load_voter_id(dut, vid)
    id_valid1, done1, out1 = await validate(dut)
    assert done1 and id_valid1, f"First vote for {vid:#07x} should be accepted"
    assert not bool(out1 & 0x10), "First vote must NOT set is_duplicate"
    dut._log.info(f"FSM PASS  {vid:#07x}  first vote accepted")

    await load_voter_id(dut, vid)
    id_valid2, done2, out2 = await validate(dut)
    assert done2,     "FSM must return to IDLE after DUPLICATE"
    assert id_valid2, "id_valid must still be 1 (voter is registered, just already voted)"
    assert bool(out2 & 0x10), "Second vote must set is_duplicate"
    dut._log.info(f"FSM PASS  {vid:#07x}  second vote blocked (is_duplicate=1)")


@cocotb.test()
async def test_tally_readback(dut):
    """Integration: after voting, uo_out[7:5] reflects the correct candidate tally."""
    dut._log.info("test_tally_readback")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    await load_voter_id(dut, 0xB0002)
    id_valid, done, _ = await validate(dut, candidate=5)
    assert done and id_valid, "Vote should be accepted"

    dut.ui_in.value = 5
    await ClockCycles(dut.clk, 1)
    tally = (int(dut.uo_out.value) >> 5) & 0x7
    assert tally == 1, f"Expected tally=1 for candidate 5, got {tally}"
    dut._log.info(f"Tally PASS  candidate=5  tally={tally}")

    await load_voter_id(dut, 0xD0099)
    id_valid2, done2, _ = await validate(dut, candidate=5)
    assert done2 and id_valid2

    dut.ui_in.value = 5
    await ClockCycles(dut.clk, 1)
    tally2 = (int(dut.uo_out.value) >> 5) & 0x7
    assert tally2 == 2, f"Expected tally=2 for candidate 5 after second vote, got {tally2}"
    dut._log.info(f"Tally PASS  candidate=5  tally={tally2} after 2 votes")


# ── MOD-01 UART unit tests ─────────────────────────────────────────────────────
#
# These test the standalone uart_inst in tb.v (CLK_FREQ=10, BAUD_RATE=1,
# BAUD_DIV=10 clocks/bit).  Each 8N1 frame = 10 bits × 10 clocks = 100 clocks.
# Three frames = 300 clocks total driven by uart_send_voter_id.
#
# WHY we do NOT use `await RisingEdge(dut.uart_data_ready_out)`:
# Icarus Verilog's VPI layer does not reliably fire value-change callbacks on
# `wire` nets that are outputs of a submodule instance accessed hierarchically.
# The callback is registered but never triggers, causing the test to hang
# indefinitely.  The fix is straightforward: send all frames sequentially,
# then wait a fixed number of extra cycles for the UART hardware to finish
# processing the last stop bit and for the frame assembler to latch the result.

@cocotb.test(skip=GL_TEST)
async def test_uart_receive_voter_id(dut):
    """MOD-01: 3-frame UART assembly must produce the correct 20-bit voter_id_out."""
    dut._log.info("test_uart_receive_voter_id")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    dut.uart_rx_in.value = 1           # idle high before transmission
    await ClockCycles(dut.clk, 2)

    target_id = 0xA0003
    await uart_send_voter_id(dut, target_id)

    # uart_send_voter_id returns after the idle gap at the end of frame 2.
    # The frame assembler sets voter_id_out during that idle gap, so the
    # value is already stable when we return.  Wait 2 extra cycles as margin.
    await ClockCycles(dut.clk, 2)

    received = int(dut.uart_voter_id_out.value)
    assert received == target_id, (
        f"UART assembled {received:#07x}, expected {target_id:#07x}"
    )
    dut._log.info(f"MOD-01 PASS  voter_id_out={received:#07x}")


@cocotb.test(skip=GL_TEST)
async def test_uart_data_ready_one_cycle(dut):
    """MOD-01: data_ready must pulse high for exactly one clock cycle."""
    dut._log.info("test_uart_data_ready_one_cycle")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    dut.uart_rx_in.value = 1
    await ClockCycles(dut.clk, 2)

    # Send in the background so we can poll data_ready concurrently.
    # data_ready pulses during the idle gap at the end of the last frame —
    # before uart_send_voter_id returns — so we must be polling WHILE
    # the send is still in progress.
    cocotb.start_soon(uart_send_voter_id(dut, 0xB0001))

    # Poll for 720 cycles (3 frames × 220 cycles + 60 margin).
    # data_ready is high for exactly 1 cycle; count how many polls see it.
    # (RisingEdge cannot be used here — see note above.)
    high_cycles = 0
    for _ in range(720):
        await ClockCycles(dut.clk, 1)
        if int(dut.uart_data_ready_out.value) == 1:
            high_cycles += 1

    assert high_cycles == 1, (
        f"data_ready was high for {high_cycles} cycle(s), expected exactly 1"
    )
    dut._log.info("MOD-01 PASS  data_ready pulse = exactly 1 cycle")
