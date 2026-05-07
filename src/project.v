`default_nettype none

module tt_um_voting_asic (
    input  wire [7:0] ui_in,    // [2:0] candidate_sel; [7:0] voter_id data byte during writes
    output wire [7:0] uo_out,   // [2:0] FSM status, [3] id_valid, [4] is_duplicate, [7:5] tally[2:0]
    input  wire [7:0] uio_in,   // [1:0] byte_sel, [2] byte_write, [3] data_ready, [7:4] voter_id[19:16]
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;

    // Protocol extraction
    wire [1:0] byte_sel    = uio_in[1:0];
    wire       byte_write  = uio_in[2];
    wire       data_ready  = uio_in[3];
    wire [2:0] candidate_in = ui_in[2:0];

    // 20-bit voter ID accumulation (two byte-write cycles then data_ready)
    // Step 1: uio_in=0b0000_0101  ui_in=voter_id[7:0]
    // Step 2: uio_in=(voter_id[19:16]<<4)|0b0000_0110  ui_in=voter_id[15:8]
    // Step 3: uio_in=0b0000_1000  ui_in[2:0]=candidate_sel
    reg [19:0] voter_id_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            voter_id_reg <= 20'b0;
        end else if (byte_write) begin
            case (byte_sel)
                2'b01: voter_id_reg[7:0]   <= ui_in[7:0];
                2'b10: begin
                    voter_id_reg[15:8]  <= ui_in[7:0];
                    voter_id_reg[19:16] <= uio_in[7:4];
                end
                default: ;
            endcase
        end
    end

    // Internal interconnects
    wire        w_id_valid, w_validate_done;
    wire        w_is_duplicate, w_check_done;
    wire        w_check_en, w_vote_en;
    wire [2:0]  w_cand_sel, w_status;
    wire [31:0] w_tally_out;

    // MOD-02: Voter ID Validator
    voter_id_validator validator (
        .clk(clk), .rst_n(rst_n),
        .voter_id_in(voter_id_reg), .data_ready(data_ready),
        .id_valid(w_id_valid), .validate_done(w_validate_done)
    );

    // MOD-03: Duplicate Vote Checker
    duplicate_checker dup_check (
        .clk(clk), .rst_n(rst_n),
        .voter_id_in(voter_id_reg), .check_en(w_check_en),
        .is_duplicate(w_is_duplicate), .check_done(w_check_done)
    );

    // MOD-04: Vote Tally Counter
    // tally_out is combinational on candidate_sel. Set ui_in[2:0] in IDLE to
    // read that candidate's lower 3 vote bits on uo_out[7:5].
    vote_tally_counter tally (
        .clk(clk), .rst_n(rst_n),
        .candidate_sel(w_cand_sel), .vote_en(w_vote_en),
        .vote_cast(), .tally_out(w_tally_out)
    );

    // MOD-05: Top-Level FSM
    mod05_fsm controller (
        .clk(clk), .rst_n(rst_n),
        .data_ready(data_ready),
        .candidate_in(candidate_in),
        .id_valid(w_id_valid), .validate_done(w_validate_done),
        .is_duplicate(w_is_duplicate), .check_done(w_check_done),
        .check_en(w_check_en), .vote_en(w_vote_en),
        .candidate_sel(w_cand_sel), .status_out(w_status)
    );

    // Output mapping
    assign uo_out[2:0] = w_status;          // FSM state (000=IDLE when done)
    assign uo_out[3]   = w_id_valid;        // 1 = registered voter
    assign uo_out[4]   = w_is_duplicate;    // 1 = already voted
    assign uo_out[7:5] = w_tally_out[2:0];  // lower 3 bits of selected candidate's tally

    wire _unused = &{ena, 1'b0};
endmodule
