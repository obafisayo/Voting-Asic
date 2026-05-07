`default_nettype none

module tt_um_voting_asic (
    input  wire [7:0] ui_in,    // [2:0] candidate_sel; [7:0] voter_id data byte during writes
    output wire [7:0] uo_out,   // [2:0] FSM status, [3] id_valid, [4] is_duplicate, [7:5] tally[2:0]
    input  wire [7:0] uio_in,   // [1:0] byte_sel, [2] byte_write, [3] data_ready, [6:4] voter_id[18:16], [7] UART_RX
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;

    // ── Byte-write bus path ───────────────────────────────────────────────────
    // Loads the 20-bit voter ID over two parallel write cycles, then triggers
    // the pipeline with data_ready.
    //
    // Step 1: ui_in=voter_id[7:0],  uio_in=0b0000_0101  (byte_sel=01, byte_write=1)
    // Step 2: ui_in=voter_id[15:8], uio_in=(voter_id[18:16]<<4)|0b0000_0110
    //         (byte_sel=10, byte_write=1; uio_in[7] is UART_RX so voter_id[19]
    //          is NOT available on this path — restrict voter IDs to 19 bits when
    //          using byte-write, or use the UART path for full 20-bit IDs.)
    // Step 3: ui_in[2:0]=candidate_sel, uio_in=0b0000_1000  (data_ready=1)

    wire [1:0] byte_sel    = uio_in[1:0];
    wire       byte_write  = uio_in[2];
    wire [2:0] candidate_in = ui_in[2:0];

    reg [19:0] voter_id_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            voter_id_reg <= 20'b0;
        end else if (byte_write) begin
            case (byte_sel)
                2'b01: voter_id_reg[7:0]   <= ui_in[7:0];
                2'b10: begin
                    voter_id_reg[15:8]  <= ui_in[7:0];
                    voter_id_reg[19:16] <= uio_in[7:4]; // uio_in[7] is UART_RX (idle-high); all
                                                         // registered IDs have bit19=1, so step 2
                                                         // always drives uio[7]=1 = UART idle
                end
                default: ;
            endcase
        end
    end

    // ── MOD-01: UART Receiver ─────────────────────────────────────────────────
    // uio_in[7] is the serial RX line (idle high, 8N1).
    // Assembles voter_id[19:0] from 3 successive frames:
    //   frame 0 → voter_id[7:0], frame 1 → voter_id[15:8], frame 2 → voter_id[19:16]
    // Pulses uart_data_ready for exactly one clock cycle when all three arrive.
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

    // ── Input mux ─────────────────────────────────────────────────────────────
    // UART path takes priority; only one source fires at a time in normal use.
    wire        combined_data_ready = uio_in[3] | uart_data_ready;
    wire [19:0] active_voter_id     = uart_data_ready ? uart_voter_id : voter_id_reg;

    // ── Internal interconnects ────────────────────────────────────────────────
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
        .data_ready(combined_data_ready),
        .candidate_in(candidate_in),
        .id_valid(w_id_valid), .validate_done(w_validate_done),
        .is_duplicate(w_is_duplicate), .check_done(w_check_done),
        .check_en(w_check_en), .vote_en(w_vote_en),
        .candidate_sel(w_cand_sel), .status_out(w_status)
    );

    // ── Output mapping ────────────────────────────────────────────────────────
    assign uo_out[2:0] = w_status;          // FSM state (000=IDLE when done)
    assign uo_out[3]   = w_id_valid;        // 1 = registered voter
    assign uo_out[4]   = w_is_duplicate;    // 1 = already voted
    assign uo_out[7:5] = w_tally_out[2:0];  // lower 3 bits of selected candidate's tally

    wire _unused = &{ena, 1'b0};
endmodule
