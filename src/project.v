`default_nettype none

module tt_um_voting_asic (
    input  wire [7:0] ui_in,    // Inputs: [7:0] Data
    output wire [7:0] uo_out,   // Outputs: [2:0] status, [0] id_valid, [1] check_done
    input  wire [7:0] uio_in,   // IO Inputs: [3:0] Control, [7:4] Upper Nibble
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    // Pin Configurations
    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0; 

    // Tiny Tapeout Control Logic
    wire [1:0] byte_sel   = uio_in[1:0];
    wire       byte_write = uio_in[2];
    wire       data_ready = uio_in[3]; // Handshake from UART/Host
    wire [2:0] candidate_in = ui_in[2:0]; // Use ui_in for candidate selection

    // 1. Data Accumulation (Voter ID)
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
            endcase
        end
    end

    // Internal Interconnect Wires
    wire w_id_valid, w_validate_done, w_is_duplicate, w_check_done;
    wire w_check_en, w_vote_en;
    wire [2:0] w_cand_sel, w_status;

    // 2. MOD-02: Voter ID Validator (Obafisayo)
    voter_id_validator validator (
        .clk(clk), .rst_n(rst_n), .voter_id_in(voter_id_reg), .data_ready(data_ready),
        .id_valid(w_id_valid), .validate_done(w_validate_done)
    );

    // 3. MOD-03: Duplicate Voter Checker (Somto)
    duplicate_checker dup_check (
        .clk(clk), .rst_n(rst_n), .voter_id_in(voter_id_reg), .check_en(w_check_en),
        .is_duplicate(w_is_duplicate), .check_done(w_check_done)
    );

    // 4. MOD-04: Vote Tally Counter (David Livingstone)
    vote_tally_counter tally (
        .clk(clk), .rst_n(rst_n), .candidate_sel(w_cand_sel), .vote_en(w_vote_en),
        .tally_out() // Note: Tally usually read out via a separate debug bus
    );

    // 5. MOD-05: Top-Level FSM (Henry)[cite: 1]
    mod05_fsm controller (
        .clk(clk), .rst_n(rst_n), .data_ready(data_ready), .candidate_in(candidate_in),
        .id_valid(w_id_valid), .validate_done(w_validate_done),
        .is_duplicate(w_is_duplicate), .check_done(w_check_done),
        .check_en(w_check_en), .vote_en(w_vote_en), .candidate_sel(w_cand_sel),
        .status_out(w_status)
    );

    // Map outputs to Tiny Tapeout Pins[cite: 1]
    assign uo_out[2:0] = w_status;     // Show FSM status on first 3 pins
    assign uo_out[3]   = w_id_valid;   // Status of ID validity
    assign uo_out[4]   = w_is_duplicate; // Status of duplicate check
    assign uo_out[7:5] = 3'b0;         // Unused

    wire _unused = &{ena, 1'b0};

endmodule