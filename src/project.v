`default_nettype none

module tt_um_voting_asic (
    input  wire [7:0] ui_in,    // [2:0] candidate_sel; [7:0] voter_id data byte during writes
    output wire [7:0] uo_out,   // [2:0] FSM status, [3] id_valid, [4] is_duplicate, [7:5] tally[2:0]
    input  wire [7:0] uio_in,   // [1:0] byte_sel, [2] byte_write, [3] data_ready, [6:4] voter_id[18:16], [7] voter_id[19]/UART_RX
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;

    // Protocol extraction (byte-write path)
    wire [1:0] byte_sel   = uio_in[1:0];
    wire       byte_write = uio_in[2];
    wire [2:0] candidate_in = ui_in[2:0];

    // 20-bit voter ID accumulation (two byte-write cycles)
    reg [19:0] voter_id_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            voter_id_reg <= 20'b0;
        end else if (byte_write) begin
            case (byte_sel)
                2'b01: voter_id_reg[7:0]   <= ui_in[7:0];
                2'b10: begin
                    voter_id_reg[15:8]  <= ui_in[7:0];
                    voter_id_reg[19:16] <= uio_in[7:4]; // uio_in[7] dual-use: voter_id[19] / UART_RX
                end
                default: ; // other combinations ignored
            endcase
        end
    end

    // MOD-01: UART Receiver — uio_in[7] is the serial RX line (idle high).
    // Assembles 20-bit voter ID from 3 successive 8N1 frames and pulses
    // uart_data_ready for exactly one cycle when all three frames arrive.
    wire [19:0] uart_voter_id;
    wire        uart_data_ready;

    mod01_uart_rx #(
        .CLK_FREQ(50_000_000),
        .BAUD_RATE(115_200)
    ) uart_rx (
        .clk          (clk),
        .rst_n        (rst_n),
        .rx           (uio_in[7]),
        .voter_id_out (uart_voter_id),
        .data_ready   (uart_data_ready)
    );

    // Input mux: UART path takes priority over byte-write path.
    // Only one source should fire at a time in normal operation.
    wire        combined_data_ready = uio_in[3] | uart_data_ready;
    wire [19:0] active_voter_id     = uart_data_ready ? uart_voter_id : voter_id_reg;

    // Internal interconnects
    wire        w_id_valid, w_validate_done;
    wire        w_is_duplicate, w_check_done;
    wire        w_check_en, w_vote_en;
    wire [2:0]  w_cand_sel, w_status;
    wire [31:0] w_tally_out;

    // MOD-02: Voter ID Validator
    voter_id_validator validator (
        .clk(clk), .rst_n(rst_n),
        .voter_id_in(active_voter_id), .data_ready(combined_data_ready),
        .id_valid(w_id_valid), .validate_done(w_validate_done)
    );

    // MOD-03: Duplicate Vote Checker
    duplicate_checker dup_check (
        .clk(clk), .rst_n(rst_n),
        .voter_id_in(active_voter_id), .check_en(w_check_en),
        .is_duplicate(w_is_duplicate), .check_done(w_check_done)
    );

    // MOD-04: Vote Tally Counter
    // tally_out is combinational on candidate_sel (= ui_in[2:0] via FSM).
    // Set ui_in[2:0] to the desired candidate index during IDLE to read
    // that candidate's lower 3 vote bits on uo_out[7:5].
    vote_tally_counter tally (
        .clk(clk), .rst_n(rst_n),
        .candidate_sel(w_cand_sel), .vote_en(w_vote_en),
        .vote_cast(), .tally_out(w_tally_out)
    );

    // MOD-05: Top-Level FSM
    mod05_fsm controller (
        .clk(clk), .rst_n(rst_n),
        .data_ready(combined_data_ready),
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
