// voting_top.v
module voting_top (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        rx,           // UART Serial input[cite: 1]
    input  wire [2:0]  candidate_in, // User vote selection[cite: 1]
    output wire [2:0]  status_out,   // Current chip status[cite: 1]
    output wire [31:0] tally_out     // Final results[cite: 1]
);

    // Internal Signal Interconnects[cite: 1]
    wire [19:0] w_voter_id;
    wire        w_data_ready, w_id_valid, w_validate_done;
    wire        w_check_en, w_is_duplicate, w_check_done, w_vote_en;
    wire [2:0]  w_cand_sel;

    // MOD-01: UART Receiver (Wisdom)[cite: 1]
    mod01_uart_rx inst_uart (
        .clk(clk), .rst_n(rst_n), .rx(rx),
        .voter_id_out(w_voter_id), .data_ready(w_data_ready)
    );

    // MOD-02: Voter ID Validator (Obafisayo)[cite: 1]
    mod02_validator inst_val (
        .clk(clk), .rst_n(rst_n), .voter_id_in(w_voter_id), .data_ready(w_data_ready),
        .id_valid(w_id_valid), .validate_done(w_validate_done)
    );

    // MOD-03: Duplicate Checker (Somto)[cite: 1]
    mod03_dup_checker inst_dup (
        .clk(clk), .rst_n(rst_n), .voter_id_in(w_voter_id), .check_en(w_check_en),
        .is_duplicate(w_is_duplicate), .check_done(w_check_done)
    );

    // MOD-04: Vote Tally Counter (David Livingstone)[cite: 1]
    mod04_tally inst_tally (
        .clk(clk), .rst_n(rst_n), .candidate_sel(w_cand_sel), .vote_en(w_vote_en),
        .tally_out(tally_out)
    );

    // MOD-05: Top-Level FSM (Henry)[cite: 1]
    mod05_fsm inst_fsm (
        .clk(clk), .rst_n(rst_n), .data_ready(w_data_ready), .candidate_in(candidate_in),
        .id_valid(w_id_valid), .validate_done(w_validate_done),
        .is_duplicate(w_is_duplicate), .check_done(w_check_done),
        .check_en(w_check_en), .vote_en(w_vote_en), .candidate_sel(w_cand_sel),
        .status_out(status_out)
    );

endmodule