// voting_top.v — full-pipeline reference design (not the TT wrapper)
// Accepts a 20-bit voter ID and a data_ready strobe over a parallel bus
// and routes it through the MOD-02 → MOD-03 → MOD-04 pipeline controlled
// by the MOD-05 FSM.  project.v is the actual Tiny Tapeout wrapper.
`default_nettype none

module voting_top (
    input  wire        clk,
    input  wire        rst_n,
    // Bus input: caller assembles the 20-bit voter ID externally and presents
    // it with data_ready high for exactly one clock cycle.
    input  wire [19:0] voter_id_in,
    input  wire        data_ready,
    input  wire [2:0]  candidate_in, // vote selection (held stable during data_ready)
    // Outputs
    output wire [2:0]  status_out,   // FSM state: 000=IDLE 011=VOTE_CAST 100=DUP 101=INVALID
    output wire        id_valid,     // 1 = registered voter
    output wire        is_duplicate, // 1 = voter already cast a ballot
    output wire [31:0] tally_out     // selected candidate's vote count (combinational)
);

    wire w_validate_done;
    wire w_check_en, w_check_done;
    wire w_vote_en;
    wire [2:0] w_cand_sel;

    // MOD-02: Voter ID Validator
    voter_id_validator inst_val (
        .clk          (clk),
        .rst_n        (rst_n),
        .voter_id_in  (voter_id_in),
        .data_ready   (data_ready),
        .id_valid     (id_valid),
        .validate_done(w_validate_done)
    );

    // MOD-03: Duplicate Vote Checker
    duplicate_checker inst_dup (
        .clk         (clk),
        .rst_n       (rst_n),
        .voter_id_in (voter_id_in),
        .check_en    (w_check_en),
        .is_duplicate(is_duplicate),
        .check_done  (w_check_done)
    );

    // MOD-04: Vote Tally Counter
    vote_tally_counter inst_tally (
        .clk          (clk),
        .rst_n        (rst_n),
        .candidate_sel(w_cand_sel),
        .vote_en      (w_vote_en),
        .vote_cast    (),
        .tally_out    (tally_out)
    );

    // MOD-05: Top-Level FSM
    mod05_fsm inst_fsm (
        .clk          (clk),
        .rst_n        (rst_n),
        .data_ready   (data_ready),
        .candidate_in (candidate_in),
        .id_valid     (id_valid),
        .validate_done(w_validate_done),
        .is_duplicate (is_duplicate),
        .check_done   (w_check_done),
        .check_en     (w_check_en),
        .vote_en      (w_vote_en),
        .candidate_sel(w_cand_sel),
        .status_out   (status_out)
    );

endmodule
