# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

# Must match MASTER_LIST in src/voter_id_validator.v
VALID_IDS   = [0xA0001, 0xA0002, 0xA0003, 0xA0004,
               0xB0001, 0xB0002, 0xC0001, 0xD0099]
INVALID_IDS = [0x00000, 0xFFFFF, 0x12345, 0xA0005, 0xD0098]


async def reset(dut):
    dut.ena.value    = 1
    dut.ui_in.value  = 0
    dut.uio_in.value = 0
    dut.rst_n.value  = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value  = 1
    await ClockCycles(dut.clk, 2)


async def load_voter_id(dut, voter_id):
    """Stream a 20-bit voter ID into the wrapper using the two-write protocol."""
    low_byte    =  voter_id        & 0xFF
    mid_byte    = (voter_id >> 8)  & 0xFF
    high_nibble = (voter_id >> 16) & 0xF

    # Write 1: voter_id[7:0] — byte_write=uio_in[2]=1, byte_sel=uio_in[1:0]=01
    dut.ui_in.value  = low_byte
    dut.uio_in.value = 0b00000101
    await RisingEdge(dut.clk)

    # Write 2: voter_id[15:8] via ui_in, voter_id[19:16] via uio_in[7:4]
    #          byte_write=1, byte_sel=10
    dut.ui_in.value  = mid_byte
    dut.uio_in.value = (high_nibble << 4) | 0b00000110
    await RisingEdge(dut.clk)

    # Deassert write strobe
    dut.ui_in.value  = 0
    dut.uio_in.value = 0
    await RisingEdge(dut.clk)


async def validate(dut):
    """Pulse data_ready and return (id_valid, validate_done) after 2 pipeline cycles."""
    # data_ready = uio_in[3]
    dut.uio_in.value = 0b00001000
    await RisingEdge(dut.clk)      # Cycle N: data_ready sampled
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 2)  # N+1: pipeline fires; N+2 ReadWrite: N+1's NBAs visible
    out = int(dut.uo_out.value)
    return bool(out & 0x1), bool(out & 0x2)


@cocotb.test()
async def test_valid_ids(dut):
    """All IDs in the master list must be accepted."""
    dut._log.info("test_valid_ids")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    for voter_id in VALID_IDS:
        await load_voter_id(dut, voter_id)
        id_valid, validate_done = await validate(dut)
        assert validate_done, f"validate_done did not pulse for ID {voter_id:#07x}"
        assert id_valid,      f"ID {voter_id:#07x} should be valid but was rejected"
        dut._log.info(f"PASS  {voter_id:#07x}  id_valid={id_valid}")


@cocotb.test()
async def test_invalid_ids(dut):
    """IDs not in the master list must be rejected."""
    dut._log.info("test_invalid_ids")
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset(dut)

    for voter_id in INVALID_IDS:
        await load_voter_id(dut, voter_id)
        id_valid, validate_done = await validate(dut)
        assert validate_done, f"validate_done did not pulse for ID {voter_id:#07x}"
        assert not id_valid,  f"ID {voter_id:#07x} should be invalid but was accepted"
        dut._log.info(f"PASS  {voter_id:#07x}  id_valid={id_valid}")


@cocotb.test()
async def test_back_to_back(dut):
    """Alternating valid/invalid IDs must each return the correct result."""
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
        dut._log.info(f"PASS  {voter_id:#07x}  id_valid={id_valid}")
