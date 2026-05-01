## How it works

This is a digital voting machine ASIC designed by Group C, built as a sequential pipeline of five cooperating modules on SkyWater 130nm via the Tiny Tapeout shuttle programme.

### Pipeline overview

```
UART Receiver (MOD-01)
      │  voter_id_out [19:0], data_ready
      ▼
Voter ID Validator (MOD-02)  ◄── this submission
      │  id_valid, validate_done
      ▼
Duplicate Vote Checker (MOD-03)
      │  is_duplicate, check_done
      ▼
Vote Tally Counter (MOD-04)
      │  vote_cast, tally_out [31:0]
      ▼
Top-Level FSM / Controller (MOD-05)
```

### MOD-02 — Voter ID Validator (Obafisayo)

The active module in this Tiny Tapeout submission. It checks an incoming 20-bit Voter ID against a hard-coded master list of 8 registered voters stored in on-chip ROM (a synthesisable `localparam` constant array).

**Comparator architecture:** An XNOR-AND tree runs in parallel across all 8 master-list entries. For each entry, every bit of the incoming ID is XNORed with the stored bit — producing all-ones only on an exact match. An AND-reduction of the 20 bits gives one match bit per entry; an OR across all entries drives `id_valid`.

**2-stage pipeline:**
- Cycle 1 (`data_ready` = 1): the voter ID is registered and the comparator tree begins evaluating.
- Cycle 2: `validate_done` pulses high for one cycle and `id_valid` is updated. `id_valid` holds its value until the next `data_ready` pulse.

**Loading a 20-bit voter ID over the 8-bit Tiny Tapeout bus** (two byte-write cycles):

| Step | `ui_in` | `uio_in` | Effect |
|------|---------|---------|--------|
| 1 | `voter_id[7:0]` | `0b0000_0101` (byte_write=1, byte_sel=01) | Latch lower byte |
| 2 | `voter_id[15:8]` | `voter_id[19:16]<<4 \| 0b0000_0110` | Latch upper byte + nibble |
| 3 | — | `0b0000_1000` (data_ready=1) | Trigger validation |

Registered Voter IDs in the master list: `0xA0001`, `0xA0002`, `0xA0003`, `0xA0004`, `0xB0001`, `0xB0002`, `0xC0001`, `0xD0099`.

### MOD-03 — Duplicate Vote Checker (Somto)

Maintains a write-once bit-map over the full 20-bit Voter ID space. When `check_en` fires, it reads the stored bit for the incoming voter ID: if 0, it marks the voter as having voted and asserts `is_duplicate = 0`; if 1, it asserts `is_duplicate = 1`. In both cases `check_done` pulses for one cycle.

### MOD-04 — Vote Tally Counter (David)

Eight independent 32-bit counters, one per candidate (selected by `candidate_sel[2:0]`). On a rising edge of `vote_en` it increments the selected counter and pulses `vote_cast` for one cycle. `tally_out[31:0]` is a combinational read of the currently selected counter.

## How to test

### Prerequisites

```bash
sudo apt install iverilog
python3 -m venv .venv && source .venv/bin/activate
pip install -r test/requirements.txt
```

### Run the simulation

```bash
cd test && make
```

All three CocoTB test cases must pass (TESTS=3 PASS=3 FAIL=0):

| Test | What it checks |
|------|---------------|
| `test_valid_ids` | All 8 registered IDs return `id_valid=1` |
| `test_invalid_ids` | 5 unregistered IDs return `id_valid=0` |
| `test_back_to_back` | Alternating valid/invalid sequence returns correct results |

### Manual stimulation via the Tiny Tapeout pins

1. Assert `rst_n` low for at least 5 clock cycles, then release.
2. Load a voter ID — two byte-write cycles (see pin protocol table in "How it works").
3. Pulse `data_ready` (`uio_in[3]`) high for exactly one clock cycle.
4. Wait 2 clock cycles.
5. Read `uo_out[0]` (`id_valid`): 1 = registered voter, 0 = unregistered.
6. `uo_out[1]` (`validate_done`) pulses high for one cycle to confirm the result is ready.

## External hardware

None.
