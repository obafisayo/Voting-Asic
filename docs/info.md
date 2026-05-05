## How it works

This is a digital voting machine ASIC designed by Group C, built as a fully integrated pipeline of five cooperating modules on SkyWater 130nm via the Tiny Tapeout shuttle programme.

### Pipeline overview

```
UART Receiver (MOD-01)
      │  voter_id_out [19:0], data_ready
      ▼
Voter ID Validator (MOD-02)
      │  id_valid, validate_done
      ▼
Duplicate Vote Checker (MOD-03)
      │  is_duplicate, check_done
      ▼
Vote Tally Counter (MOD-04)
      │  vote_cast, tally_out [31:0]
      ▼
Top-Level FSM / Controller (MOD-05) ──► controls check_en, vote_en, candidate_sel
```

All modules are integrated in `src/project.v` under the `tt_um_voting_asic` top-level wrapper.

### MOD-05 — Top-Level FSM (Henry)

A 6-state Mealy FSM that sequences the pipeline on each voter request:

| State | Meaning |
|-------|---------|
| `IDLE` (000) | Waiting for data_ready |
| `VALIDATING` (001) | voter_id_validator running (2-cycle pipeline) |
| `CHECKING` (010) | duplicate_checker running |
| `VOTE_CAST` (011) | Vote accepted — vote_en pulsed for one cycle |
| `DUPLICATE` (100) | Voter already voted — rejected |
| `INVALID` (101) | ID not in master list — rejected |

`uo_out[2:0]` exposes the FSM status in real time so external logic can observe pipeline progress.

### MOD-02 — Voter ID Validator (Obafisayo)

Checks an incoming 20-bit Voter ID against a hard-coded master list of 8 registered voters stored in on-chip ROM (a synthesisable `localparam` constant array).

**Comparator architecture:** An XNOR-AND tree runs in parallel across all 8 master-list entries. For each entry, every bit of the incoming ID is XNORed with the stored bit — producing all-ones only on an exact match. An AND-reduction of the 20 bits gives one match bit per entry; an OR across all entries drives `id_valid`.

**2-stage pipeline:** latches voter ID on `data_ready`, asserts `validate_done` + updates `id_valid` one cycle later.

Registered Voter IDs: `0xA0001`, `0xA0002`, `0xA0003`, `0xA0004`, `0xB0001`, `0xB0002`, `0xC0001`, `0xD0099`.

### MOD-03 — Duplicate Vote Checker (Somto)

Maintains a write-once bit-map over the voter ID space. When `check_en` fires, it reads the stored bit: if 0, marks the voter as having voted and asserts `is_duplicate = 0`; if 1, asserts `is_duplicate = 1`. `check_done` pulses for one cycle in both cases.

### MOD-04 — Vote Tally Counter (David)

Eight independent 32-bit counters, one per candidate (selected by `candidate_sel[2:0]`). On a rising edge of `vote_en` it increments the selected counter and pulses `vote_cast` for one cycle.

**Loading a 20-bit voter ID over the 8-bit Tiny Tapeout bus** (two byte-write cycles then trigger):

| Step | `ui_in` | `uio_in` | Effect |
|------|---------|---------|--------|
| 1 | `voter_id[7:0]` | `0b0000_0101` | Latch lower byte (byte_sel=01, byte_write=1) |
| 2 | `voter_id[15:8]` | `(voter_id[18:16]<<4) \| 0b0000_0110` | Latch mid byte + bits [18:16] via uio[6:4] (byte_sel=10) |
| 3 | `candidate_sel[2:0]` | `0b0000_1000` | Pulse data_ready; full pipeline starts |

Note: `uio[7]` is now dedicated to UART RX. `voter_id[19]` is not loadable via the byte-write protocol (use UART mode to supply IDs where bit 19 matters, or restrict voter IDs to 19 bits in byte-write mode).

**UART input path** — Alternative to byte-write: send three 8N1 frames at 115200 baud on `uio[7]` (idle high). Frame order: `voter_id[7:0]`, `voter_id[15:8]`, `voter_id[19:16]` (lower nibble only). After the third frame the UART pulses `data_ready` internally and the pipeline starts automatically — no manual byte-write or `uio[3]` pulse needed.

After the pipeline completes (~6 clock cycles): `uo_out[2:0]` returns to `000` (IDLE). `uo_out[3]` holds `id_valid`. `uo_out[4]` holds `is_duplicate`. `uo_out[7:5]` continuously shows the lower 3 bits of the currently selected candidate's tally — set `ui_in[2:0]` to the candidate index (0–7) to select which counter to read.

## How to test

### Prerequisites

```
sudo apt install iverilog
python3 -m venv .venv
source .venv/bin/activate
pip install -r test/requirements.txt
```

### Run the full simulation

```
cd test && make
```

All 9 CocoTB test cases must pass (TESTS=9 PASS=9 FAIL=0):

| Test | Module | What it checks |
|------|--------|---------------|
| test_valid_ids | MOD-02 | All 8 registered IDs reach VOTE_CAST, id_valid=1 |
| test_invalid_ids | MOD-02 | 5 unregistered IDs reach INVALID, id_valid=0 |
| test_back_to_back | MOD-02 | Alternating valid/invalid sequence |
| test_duplicate_checker_first_vote | MOD-03 | First submission accepted |
| test_duplicate_checker_second_vote | MOD-03 | Repeat submission blocked |
| test_duplicate_checker_new_vs_repeat | MOD-03 | Accept then block same ID |
| test_vote_tally_single_candidate | MOD-04 | Counter increments correctly |
| test_vote_tally_multiple_candidates | MOD-04 | Separate counters per candidate |
| test_vote_tally_no_spurious_votes | MOD-04 | Edge detector prevents double-count |

MOD-03 and MOD-04 tests exercise the modules directly via standalone testbench instances (not through the TT wrapper), so they are skipped during gate-level simulation (`make GATES=yes`), which only tests the synthesised `tt_um_voting_asic`.

### Manual stimulation via the Tiny Tapeout pins

1. Assert `rst_n` low for at least 5 clock cycles, then release.
2. Load a voter ID using the two byte-write protocol (see table above).
3. Pulse `data_ready` (`uio_in[3]`) high for exactly one clock cycle, with `ui_in[2:0]` set to the desired candidate number.
4. Wait ~6 clock cycles for the pipeline to complete.
5. Read `uo_out[3]` (`id_valid`): 1 = registered voter, 0 = unregistered.
6. Read `uo_out[4]` (`is_duplicate`): 1 = voter already cast a ballot.
7. Read `uo_out[2:0]` (`status`): 011 = VOTE_CAST, 100 = DUPLICATE, 101 = INVALID.
8. To read vote tallies: with `uo_out[2:0]` = 000 (IDLE), set `ui_in[2:0]` to the candidate index; `uo_out[7:5]` shows that candidate's vote count (lower 3 bits, range 0–7).

## External hardware

None.
