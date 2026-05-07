`default_nettype none
`timescale 1ns / 1ps

/* This testbench instantiates the module and makes some convenient wires
   that can be driven / tested by the cocotb test.py.
*/
module tb ();

  // Dump the signals to a FST file. You can view it with gtkwave or surfer.
  initial begin
    $dumpfile("tb.fst");
    $dumpvars(0, tb);
    #1;
  end

  // ── Shared clock and reset ──────────────────────────────────
  reg clk;
  reg rst_n;
  reg ena;

  // ── Top-level TT wrapper ────────────────────────────────────
  reg [7:0] ui_in;
  reg [7:0] uio_in;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;
`ifdef GL_TEST
  wire VPWR = 1'b1;
  wire VGND = 1'b0;
`endif

  tt_um_voting_asic user_project (
`ifdef GL_TEST
      .VPWR(VPWR),
      .VGND(VGND),
`endif
      .ui_in  (ui_in),
      .uo_out (uo_out),
      .uio_in (uio_in),
      .uio_out(uio_out),
      .uio_oe (uio_oe),
      .ena    (ena),
      .clk    (clk),
      .rst_n  (rst_n)
  );

`ifndef GL_TEST
  // ── MOD-01: UART Receiver (fast-baud standalone for unit tests) ────────────
  // CLK_FREQ=20, BAUD_RATE=1  →  BAUD_DIV=20, HALF_BAUD=10
  // 20 clocks/bit instead of real 434 cycles/bit (50 MHz / 115200 baud).
  // BAUD_DIV must be ≥14: the DATA state samples every BAUD_DIV+1 cycles
  // (one extra clock for baud_cnt reload), so with BAUD_DIV=10 the 8th
  // sample falls into the stop-bit region and bit 7 is always read as 1.
  reg         uart_rx_in;
  wire [19:0] uart_voter_id_out;
  wire        uart_data_ready_out;

  mod01_uart_rx #(
      .CLK_FREQ(20),
      .BAUD_RATE(1)
  ) uart_inst (
      .clk          (clk),
      .rst_n        (rst_n),
      .rx           (uart_rx_in),
      .voter_id_out (uart_voter_id_out),
      .data_ready   (uart_data_ready_out)
  );

  // ── MOD-03: Duplicate Vote Checker ─────────────────────────
  reg  [19:0] dc_voter_id;
  reg         dc_check_en;
  wire        dc_is_duplicate;
  wire        dc_check_done;

  duplicate_checker dc_inst (
      .voter_id_in (dc_voter_id),
      .check_en    (dc_check_en),
      .clk         (clk),
      .rst_n       (rst_n),
      .is_duplicate(dc_is_duplicate),
      .check_done  (dc_check_done)
  );

  // ── MOD-04: Vote Tally Counter ──────────────────────────────
  reg        vtc_vote_en;
  reg  [2:0] vtc_candidate_sel;
  wire       vtc_vote_cast;
  wire [31:0] vtc_tally_out;

  vote_tally_counter vtc_inst (
      .clk          (clk),
      .rst_n        (rst_n),
      .vote_en      (vtc_vote_en),
      .candidate_sel(vtc_candidate_sel),
      .vote_cast    (vtc_vote_cast),
      .tally_out    (vtc_tally_out)
  );
`endif

endmodule
