<!---
This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.

## How it works

Explain how your project works

## How to test

Explain how to use your project

## External hardware

List external hardware used in your project (e.g. PMOD, LED display, etc), if any
-->

## How it works

MOD-02 is the Voter ID Validator module of a Voting ASIC group project. It checks an incoming 20-bit Voter ID against a hard-coded master list of registered voters stored in on-chip ROM (synthesised as a localparam constant array).

**Comparator architecture:** An XNOR-AND tree runs in parallel across all 8 master-list entries. For each entry, every bit of the incoming ID is XNORed with the corresponding stored bit — producing all-ones only on an exact match. An AND-reduction of the 20 bits gives a single match bit per entry; an OR across all entries gives the final `id_valid` signal.

**Pipeline:** The design uses a 2-stage synchronous pipeline so that the combinational path is broken and timing constraints are met at 50 MHz.
- Cycle 1 (data_ready = 1): the voter ID is registered internally and the comparator tree begins evaluating.
- Cycle 2: `validate_done` pulses high for one cycle and `id_valid` is updated with the comparison result. `id_valid` holds its value until the next `data_ready` pulse.

**Loading a 20-bit voter ID via the Tiny Tapeout 8-bit bus:** The wrapper accepts the ID over two byte-write cycles controlled by `uio_in`:

| Step | ui_in | uio_in | Effect |
|------|-------|--------|--------|
| 1 | voter_id[7:0] | `0b0000_0101` (byte_write=1, byte_sel=01) | Latch lower byte |
| 2 | voter_id[15:8] | `(voter_id[19:16] << 4) \| 0b0000_0110` | Latch upper byte + nibble |
| 3 | — | `0b0000_1000` (data_ready=1) | Trigger validation |

## How to test

1. Assert reset (`rst_n` low for ≥ 5 cycles), then release.
2. Load a 20-bit voter ID using the two-write protocol above (Steps 1 and 2).
3. Pulse `data_ready` (Step 3) for exactly one clock cycle.
4. Wait 2 clock cycles.
5. Read `uo_out[0]` (`id_valid`) — 1 means the ID is registered, 0 means it is not.
6. `uo_out[1]` (`validate_done`) pulses high for one cycle to confirm the result is ready.

Registered IDs in the master list: `0xA0001`, `0xA0002`, `0xA0003`, `0xA0004`, `0xB0001`, `0xB0002`, `0xC0001`, `0xD0099`.

Run the CocoTB simulation locally with:
```
cd test && make
```

## External hardware

None.
